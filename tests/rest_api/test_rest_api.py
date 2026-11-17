"""Лаба 6: автоматизоване тестування REST API (pytest + requests) для SUT B, варіант 03."""
import pytest

MISSING_ID = 9000000000000000000  # дуже великий id, якого точно немає в БД (менше за 2^63-1)


def assert_error(response, status, code, message=None):
    """Перевірка error contract: статус, JSON і рівно два поля code та message."""
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"code", "message"}
    assert body["code"] == code
    assert body["message"]  # повідомлення не порожнє
    if message is not None:
        assert body["message"] == message


# ===============================================================
# 1-2. POST і GET обладнання
# ===============================================================
def test_create_equipment_returns_201_and_resource(api, unique):
    code = unique("API-E")

    response = api.post("/equipment", {"code": code, "daily_rate": 10000, "stock": 10})

    assert response.status_code == 201
    body = response.json()
    assert isinstance(body["id"], int) and body["id"] > 0  # id видала БД
    assert body["code"] == code
    assert body["daily_rate"] == 10000
    assert body["stock"] == 10
    assert response.headers["Location"] == f"/equipment/{body['id']}"


def test_get_equipment_by_id_returns_200_and_same_data(api, make_equipment):
    created = make_equipment(daily_rate=2500, stock=7)

    response = api.get(f"/equipment/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created  # те, що прочитали, збігається з тим, що створили


# ===============================================================
# 3. GET неіснуючого ресурсу: 404 і error contract
# ===============================================================
def test_get_missing_equipment_returns_404_error_contract(api):
    response = api.get(f"/equipment/{MISSING_ID}")

    assert_error(response, 404, "NOT_FOUND", "Обладнання не знайдено")


def test_get_missing_rental_returns_404_error_contract(api):
    response = api.get(f"/rentals/{MISSING_ID}")

    assert_error(response, 404, "NOT_FOUND", "Оренду не знайдено")


# ===============================================================
# POST і GET оренди
# ===============================================================
def test_create_rental_returns_201_and_resource(api, make_equipment, unique):
    equipment = make_equipment(daily_rate=2000, stock=5)
    reference = unique("API-R")

    response = api.post("/rentals", {"reference": reference, "equipment_id": equipment["id"],
                                     "quantity": 2, "days": 3, "premium": False})

    assert response.status_code == 201
    body = response.json()
    assert isinstance(body["id"], int) and body["id"] > 0
    assert body["reference"] == reference
    assert body["days"] == 3 and body["premium"] is False
    assert body["total"] == 12000  # 2000 * 2 * 3, без знижки
    assert body["late_fee"] == 0
    assert body["status"] == "Active"
    assert body["item"]["equipment_id"] == equipment["id"]
    assert body["item"]["quantity"] == 2
    assert body["item"]["daily_rate"] == 2000  # знімок ціни
    assert response.headers["Location"] == f"/rentals/{body['id']}"


def test_get_rental_by_id_returns_200_and_same_data(api, make_equipment, make_rental):
    created = make_rental(make_equipment(), quantity=2, days=4)

    response = api.get(f"/rentals/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


# ===============================================================
# 4. Action endpoint: повернення оренди
# ===============================================================
def test_return_rental_returns_200_and_new_state(api, make_equipment, make_rental):
    rental = make_rental(make_equipment(daily_rate=1000), quantity=1, days=2)

    response = api.post(f"/rentals/{rental['id']}/return", {"overdue_days": 4})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == rental["id"]
    assert body["status"] == "Returned"
    assert body["total"] == rental["total"]  # початкова сума не змінюється
    assert body["late_fee"] == 0  # у цьому варіанті доплати немає


# ===============================================================
# 5-6. Повторна дія: 409 і незмінність ресурсу після відхилення
# ===============================================================
def test_repeated_return_returns_409_error_contract(api, make_equipment, make_rental):
    rental = make_rental(make_equipment())
    api.post(f"/rentals/{rental['id']}/return", {"overdue_days": 0})

    response = api.post(f"/rentals/{rental['id']}/return", {"overdue_days": 7})

    assert_error(response, 409, "RENTAL_CONFLICT", "Оренду вже повернено")


def test_rental_unchanged_after_rejected_return(api, make_equipment, make_rental):
    rental = make_rental(make_equipment(), quantity=1, days=3)
    api.post(f"/rentals/{rental['id']}/return", {"overdue_days": 0})
    state_after_first_return = api.get(f"/rentals/{rental['id']}").json()

    rejected = api.post(f"/rentals/{rental['id']}/return", {"overdue_days": 30})

    assert rejected.status_code == 409
    state_after_rejection = api.get(f"/rentals/{rental['id']}").json()
    assert state_after_rejection == state_after_first_return  # відхилена дія нічого не змінила
    assert state_after_rejection["status"] == "Returned"


def test_rental_rejected_for_insufficient_stock_returns_409(api, make_equipment, unique):
    equipment = make_equipment(daily_rate=1000, stock=2)

    response = api.post("/rentals", {"reference": unique("API-R"), "equipment_id": equipment["id"],
                                     "quantity": 3, "days": 1, "premium": False})

    assert_error(response, 409, "RENTAL_CONFLICT", "Недостатньо обладнання")
    assert api.get(f"/equipment/{equipment['id']}").json() == equipment  # обладнання не змінилось


def test_duplicate_equipment_code_returns_409_and_keeps_original(api, make_equipment):
    original = make_equipment(daily_rate=1500, stock=3)

    response = api.post("/equipment", {"code": original["code"], "daily_rate": 9999, "stock": 99})

    assert_error(response, 409, "DUPLICATE_RESOURCE")
    assert api.get(f"/equipment/{original['id']}").json() == original


def test_duplicate_rental_reference_returns_409_and_keeps_original(api, make_equipment, make_rental):
    equipment = make_equipment()
    first = make_rental(equipment, quantity=1, days=2)

    response = api.post("/rentals", {"reference": first["reference"], "equipment_id": equipment["id"],
                                     "quantity": 2, "days": 4, "premium": True})

    assert_error(response, 409, "DUPLICATE_RESOURCE")
    assert api.get(f"/rentals/{first['id']}").json() == first


# ===============================================================
# Інші помилки: 404 для оренди без обладнання, 400 для некоректних даних
# ===============================================================
def test_rental_for_missing_equipment_returns_404(api, unique):
    response = api.post("/rentals", {"reference": unique("API-R"), "equipment_id": MISSING_ID,
                                     "quantity": 1, "days": 1, "premium": False})

    assert_error(response, 404, "NOT_FOUND", "Обладнання не знайдено")


def test_return_missing_rental_returns_404(api):
    response = api.post(f"/rentals/{MISSING_ID}/return", {"overdue_days": 0})

    assert_error(response, 404, "NOT_FOUND", "Оренду не знайдено")


@pytest.mark.parametrize("override", [
    pytest.param({"quantity": 0}, id="quantity_0"),
    pytest.param({"quantity": 21}, id="quantity_21"),
    pytest.param({"days": 0}, id="days_0"),
    pytest.param({"days": 31}, id="days_31"),
    pytest.param({"quantity": "abc"}, id="quantity_not_a_number"),
    pytest.param({"reference": ""}, id="reference_empty"),
])
def test_invalid_rental_data_returns_400(api, make_equipment, unique, override):
    equipment = make_equipment(stock=20)
    body = {"reference": unique("API-R"), "equipment_id": equipment["id"], "quantity": 1, "days": 1, "premium": False}
    body.update(override)

    response = api.post("/rentals", body)

    assert_error(response, 400, "INVALID_REQUEST")


def test_missing_field_returns_400(api, unique):
    response = api.post("/equipment", {"code": unique("API-E"), "daily_rate": 1000})  # немає stock

    assert_error(response, 400, "INVALID_REQUEST", "Некоректні дані запиту")


@pytest.mark.parametrize("override", [
    pytest.param({"daily_rate": 99}, id="rate_below_min"),
    pytest.param({"daily_rate": 1000001}, id="rate_above_max"),
    pytest.param({"stock": -1}, id="stock_negative"),
    pytest.param({"code": ""}, id="code_empty"),
    pytest.param({"code": "   "}, id="code_spaces"),
])
def test_invalid_equipment_data_returns_400(api, unique, override):
    body = {"code": unique("API-E"), "daily_rate": 1000, "stock": 1}
    body.update(override)

    response = api.post("/equipment", body)

    assert_error(response, 400, "INVALID_REQUEST")  # відхилила БД (CHECK), API перетворив на 400


@pytest.mark.parametrize("overdue_days", [-1, 36501], ids=["negative", "above_36500"])
def test_invalid_overdue_days_returns_400_and_rental_unchanged(api, make_equipment, make_rental, overdue_days):
    rental = make_rental(make_equipment())

    response = api.post(f"/rentals/{rental['id']}/return", {"overdue_days": overdue_days})

    assert_error(response, 400, "INVALID_REQUEST")
    assert api.get(f"/rentals/{rental['id']}").json() == rental  # лишилась Active


# ===============================================================
# 7. Персональне правило: знижка 15% для premium від 5 днів (параметризація)
# ===============================================================
@pytest.mark.parametrize("premium, days, rate, quantity, expected_total", [
    pytest.param(True, 4, 1000, 1, 4000, id="premium_4_days_no_discount"),
    pytest.param(True, 5, 1000, 1, 4250, id="premium_5_days_discount"),
    pytest.param(False, 5, 1000, 1, 5000, id="regular_5_days_no_discount"),
    pytest.param(True, 5, 101, 1, 430, id="discount_rounded_down"),
    pytest.param(True, 7, 333, 3, 5945, id="discount_rounded_down_many_units"),
    pytest.param(True, 30, 1000000, 20, 510000000, id="premium_max_values"),
])
def test_premium_discount_rule_via_api(api, make_equipment, make_rental, premium, days, rate, quantity, expected_total):
    equipment = make_equipment(daily_rate=rate, stock=20)

    rental = make_rental(equipment, quantity=quantity, days=days, premium=premium)

    assert rental["total"] == expected_total
    assert rental["premium"] is premium
    stored = api.get(f"/rentals/{rental['id']}").json()  # те саме збережено в системі
    assert stored["total"] == expected_total
    assert stored["item"]["daily_rate"] == rate  # знімок ціни без знижки


# ===============================================================
# 8. Workflow: POST -> GET -> action -> GET, id передається динамічно
# ===============================================================
def test_workflow_create_get_return_get(api, unique):
    # крок 1: створюємо обладнання, id беремо з відповіді
    equipment = api.post("/equipment", {"code": unique("API-E"), "daily_rate": 1000, "stock": 5}).json()

    # крок 2: створюємо оренду, підставивши id обладнання з кроку 1
    created = api.post("/rentals", {"reference": unique("API-R"), "equipment_id": equipment["id"],
                                    "quantity": 2, "days": 5, "premium": True})
    assert created.status_code == 201
    rental_id = created.json()["id"]  # id оренди з відповіді

    # крок 3: читаємо оренду за цим id, вона Active зі знижкою
    before = api.get(f"/rentals/{rental_id}")
    assert before.status_code == 200
    assert before.json()["status"] == "Active"
    assert before.json()["total"] == 8500  # 2*1000*5 = 10000, мінус 15%

    # крок 4: повертаємо
    returned = api.post(f"/rentals/{rental_id}/return", {"overdue_days": 3})
    assert returned.status_code == 200

    # крок 5: читаємо ще раз, стан змінився, сума збереглась
    after = api.get(f"/rentals/{rental_id}")
    assert after.status_code == 200
    assert after.json()["status"] == "Returned"
    assert after.json()["total"] == 8500
    assert after.json()["late_fee"] == 0
