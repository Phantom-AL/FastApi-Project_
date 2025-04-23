from collections import defaultdict
from datetime import datetime, date
from io import BytesIO
from typing import Annotated

import pandas
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy import select, func, extract
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import engine, AsyncSessionLocal
from app.models import Base, Credits, Payments, Plans, Dictionary
from pydantic import BaseModel
import asyncio


app = FastAPI()


@app.on_event("startup")
async def on_startup():
    # Выполняем создание всех таблиц при старте приложения FastAP
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# Зависимость для получения async-сессии
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


# Зависимость для получения async-сессии
DbSession = Annotated[AsyncSession, Depends(get_db)]


@app.get('/user_credits/{user_id}')
async def get_user_credits(db: DbSession, user_id: int):
    """
    Метод для получения информации о кредитах клиента
    """
    response = select(Credits).where(Credits.user_id == user_id)
    result = await db.execute(response)
    credits = result.scalars().all()

    if not credits:
        raise HTTPException(status_code=404, detail="Не найдено кредитов для этого пользователя")

    final_result = []

    # Обработка каждого кредита
    for credit in credits:
        credit_info = {
            "issuance_date": credit.issuance_date,
            "status": bool(credit.actual_return_date)
        }

        # Запрос на получение платежей по кредиту
        result = await db.execute(select(Payments).where(Payments.credit_id == credit.id))
        payments = result.scalars().all()

        # Вычисление суммы основной суммы и процентов по платежам
        principal_sum = sum(payment.sum for payment in payments if payment.type_id == 1)
        interest_sum = sum(payment.sum for payment in payments if payment.type_id == 2)

        if credit.actual_return_date:
            credit_info.update({
                "actual_return_date": credit.actual_return_date,
                "body": credit.body,
                "percent": credit.percent,
                "total_payments": principal_sum + interest_sum
            })
        else:
            today = datetime.today().date()
            overdue_days = (today - credit.return_date.date()).days if today > credit.return_date.date() else 0
            credit_info.update({
                "return_date": credit.return_date,
                "overdue_days": overdue_days,
                "body": credit.body,
                "percent": credit.percent,
                "principal_payments": principal_sum,
                "interest_payments": interest_sum
            })

        final_result.append(credit_info)

    return final_result


# Вставка планов из загружаемого файла
@app.post('/plans_insert')
async def plans_insert(db: DbSession, file: UploadFile):
    """
    Метод для загрузки планов на новый месяц
    """
    contents = await file.read()
    try:
        df = pandas.read_excel(BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка при чтении файла: {str(e)}")

    required_columns = ['month', 'category', 'amount']  # Ожидаемые столбцы
    # Проверка на наличие нужных столбцов в файле
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise HTTPException(status_code=400, detail=f"Не верное название столбцов, должны быть: month, category, amount ")

    plans_data = df.to_dict('records')

    for plan_data in plans_data:

        month = plan_data['month']
        category = plan_data['category'].strip().lower()
        amount = plan_data['amount']

        try:
            period = pandas.to_datetime(str(month)).date()
        except Exception:
            raise HTTPException(status_code=400, detail=f"Неверный формат даты: {month}")

        # Проверка, что в дате стоит первый день месяца
        if period.day != 1:
            raise HTTPException(status_code=400, detail=f'У даты {month} должен быть первый день месяца')

        # Получение категории
        response = select(Dictionary).where(Dictionary.name == category)
        result = await db.execute(response)
        category_obj = result.scalars().first()

        if not category_obj:
            raise HTTPException(status_code=400, detail=f"Категория '{category}' не найдена")

        # Проверка, не существует ли уже план с такой категорией и периодом
        response = select(Plans).where(Plans.period == period, Plans.category_id == category_obj.id)
        result = await db.execute(response)
        existing = result.scalars().first()

        if existing:
            raise HTTPException(status_code=409, detail=f"План {period} с категорией {category} уже существует")

        if amount is None or amount < 0:
            raise HTTPException(status_code=400, detail=f"Неверно указана сумма")

        # Добавление нового плана
        new_plan = Plans(period=period, sum=amount, category_id=category_obj.id)
        db.add(new_plan)

    await db.commit()
    return {'status': 'OK', "records": plans_data}


@app.get('/plans_performance')
async def plans_performance(db: DbSession, check_date: date):
    """
    Метод для получения информации о выполнении планов на определенную дату
    """
    result = []
    first_day_of_month = check_date.replace(day=1)

    # Получаем все категории из словаря
    response = await db.execute(select(Dictionary.id, Dictionary.name))
    category_map = dict(response.all())  # {id: name}

    # Получаем планы на месяц
    response = await db.execute(select(Plans).where(Plans.period == first_day_of_month))
    plans = response.scalars().all()

    # Основная логика
    for plan in plans:
        category_name = category_map.get(plan.category_id, "Неизвестно")
        actual_sum = 0

        if category_name == "Выдача кредитов":
            response = await db.execute(
                select(func.sum(Credits.body)).where(
                    Credits.issuance_date.between(first_day_of_month, check_date)
                )
            )
            actual_sum = response.scalar() or 0

        elif category_name == "Сбор платежей":
            response = await db.execute(
                select(func.sum(Payments.sum)).where(
                    Payments.payment_date.between(first_day_of_month, check_date)
                )
            )
            actual_sum = response.scalar() or 0

        percent = (actual_sum / plan.sum * 100) if plan.sum else 0

        result.append({
            "month": plan.period.month,
            "category": category_name,
            "sum": float(plan.sum),
            "actual_sum": float(actual_sum),
            "completion_percent": round(percent, 2)
        })

    return result


def init_month_data():
    return {
        'issuance_count': 0,
        'issuance_sum': 0,
        'plan_issuance_sum': 0,
        'plan_gather_sum': 0,
        'payment_count': 0,
        'payment_sum': 0
    }


async def get_records_by_year(db: DbSession, model, year: int, date_column: str):
    # Получаем столбец с датой из модели
    column = getattr(model, date_column)

    # Создаем запрос с извлечением года
    response = select(model).where(extract('year', column) == year)
    result_exec = await db.execute(response)
    return result_exec.scalars().all()


def calculate_percent(numerator, denominator):
    return round((numerator / denominator * 100), 2) if denominator else 0


@app.get('/year_performance')
async def year_performance(db: DbSession, year: int):
    """
    Метод получения сводной информации за заданный год. Группировка по-месячная
    """
    result = []

    # Получаем все записи
    plans, credits, payments = await asyncio.gather(
        get_records_by_year(db, Plans, year, 'period'),
        get_records_by_year(db, Credits, year, 'issuance_date'),
        get_records_by_year(db, Payments, year, 'payment_date'),
    )

    monthly_data = defaultdict(init_month_data)

    # Подсчет данных по кредитам
    for credit in credits:
        data = monthly_data[credit.issuance_date.month]
        data['issuance_count'] += 1
        data['issuance_sum'] += credit.body

    # Подсчет данных по планам
    for plan in plans:
        data = monthly_data[plan.period.month]
        if plan.category_id == 3:
            data['plan_issuance_sum'] += plan.sum
        elif plan.category_id == 4:
            data['plan_gather_sum'] += plan.sum

    # Подсчет данных по платежам
    for payment in payments:
        data = monthly_data[payment.payment_date.month]
        data['payment_count'] += 1
        data['payment_sum'] += payment.sum

    # Общая сумма по всем кредитам за весь год
    total_issuance_sum = 0

    # Общая сумма по всем платежам за весь год
    total_payment_sum = 0

    for data in monthly_data.values():
        total_issuance_sum += data['issuance_sum']
        total_payment_sum += data['payment_sum']

    # Формирование финального результата
    for month, data in sorted(monthly_data.items()):
        result.append({
            'month': month,
            'year': year,
            'issuances_count': data['issuance_count'],
            'issuance_sum': data['issuance_sum'],
            'plan_issuance_sum': data['plan_issuance_sum'],
            'percent_issuance': calculate_percent(data['issuance_sum'], data['plan_issuance_sum']),
            'payments_count': data['payment_count'],
            'payment_sum': data['payment_sum'],
            'plan_gather_sum': data['plan_gather_sum'],
            'percent_gather': calculate_percent(data['payment_sum'], data['plan_gather_sum']),
            'percent_issuance_of_year': calculate_percent(data['issuance_sum'], total_issuance_sum),
            'percent_payment_of_year': calculate_percent(data['payment_sum'], total_payment_sum),
        })

    return result
