"""Лаба 8: regression-набір SUT B після виправлення нестабільних тестів.
Кожен тест створює власні дані, не покладається на інші тести, порядок запуску та паузи (sleep)."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from rental.models import Equipment, RentalRequest, RentalStatus as S
from rental.repositories import PostgresEquipmentRepository, PostgresRentalRepository
from rental.service import RentalRejectedError, RentalService

pytestmark = pytest.mark.regression  # усі тести цього файлу належать до повного regression-набору


# ===============================================================
# Допоміжні функції (вхідні дані кожного тесту створюються заново)
# ===============================================================
def new_equipment(sut, daily_rate=10000, stock=5):
    return sut.equipment.create(Equipment(0, str(uuid4()), daily_rate, stock))  # унікальний код


def new_request(equipment):
    return RentalRequest(str(uuid4()), equipment.id, 1, 2, False)


def wait_until(condition, timeout=10.0, interval=0.02):
    """Очікування умови з обмеженням за часом (замість фіксованого sleep)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return False


class GatedPolicy:
    """Політика, яка чекає сигналу від тесту. Дає детерміновану паузу без sleep."""

    def __init__(self):
        self.entered = threading.Event()  # політику викликано
        self.release = threading.Event()  # тест дозволив продовжити

    def is_allowed(self, equipment, quantity, days):
        self.entered.set()
        if not self.release.wait(timeout=10):
            raise TimeoutError("Тест не відпустив політику")
        return True


# ===============================================================
# Smoke: критичні сценарії (також входять у повний regression)
# ===============================================================
@pytest.mark.smoke
def test_create_rental(sut):
    saved = sut.service.rent(new_request(new_equipment(sut)))  # без спільної глобальної змінної
    assert saved.status == S.ACTIVE
    assert sut.rentals.find_by_id(saved.id) == saved


@pytest.mark.smoke
def test_return_rental(sut):
    saved = sut.service.rent(new_request(new_equipment(sut)))  # власна оренда, а не з попереднього тесту
    returned = sut.service.return_rental(saved.id, 0)
    assert returned.status == S.RETURNED
    assert returned.late_fee == 0
    assert sut.rentals.find_by_id(saved.id) == returned


@pytest.mark.smoke
def test_rental_amount(sut):
    equipment = new_equipment(sut)
    saved = sut.service.rent(new_request(equipment))
    stored = sut.rentals.find_by_id(saved.id)
    assert stored.total == 20000
    assert stored.item.equipment_id == equipment.id
    assert stored.item.quantity == 1
    assert stored.item.daily_rate == 10000


@pytest.mark.smoke
def test_stock_rejection(sut):
    equipment = new_equipment(sut)
    with pytest.raises(RentalRejectedError):
        sut.service.rent(RentalRequest(str(uuid4()), equipment.id, 6, 2, False))
    assert sut.rentals.find_rentals(equipment.id, S.ACTIVE) == []


# ===============================================================
# Решта regression-набору
# ===============================================================
def test_equipment_stock(sut):
    saved = sut.equipment.create(Equipment(0, str(uuid4()), 10000, 5))  # унікальний код замість фіксованого
    assert sut.equipment.find_by_id(saved.id).stock == 5


def test_equipment_rate(sut):
    saved = sut.equipment.create(Equipment(0, str(uuid4()), 15000, 3))  # не конфліктує з іншими тестами
    assert sut.equipment.find_by_id(saved.id).daily_rate == 15000


def test_rental_after_policy_check(sut):
    equipment = new_equipment(sut)
    data = new_request(equipment)
    gate = GatedPolicy()

    def rent():
        with sut.open_connection() as db:  # окреме з'єднання для потоку
            service = RentalService(PostgresEquipmentRepository(db), PostgresRentalRepository(db), gate)
            return service.rent(data)

    with ThreadPoolExecutor(max_workers=1) as executor:
        operation = executor.submit(rent)
        try:
            # чекаємо умову: політика викликана (або потік уже завершився помилкою)
            wait_until(lambda: gate.entered.is_set() or operation.done())
            assert gate.entered.is_set(), operation.result(timeout=1)  # якщо потік упав, покаже справжню причину
            # поки політика не відповіла, оренди в БД ще немає
            assert sut.rentals.find_rentals(equipment.id, S.ACTIVE) == []
        finally:
            gate.release.set()  # політика відповідає "дозволено"
        operation.result(timeout=10)  # чекаємо завершення оренди (і прокидаємо помилку, якщо була)

    saved = sut.rentals.find_rentals(equipment.id, S.ACTIVE)
    assert len(saved) == 1
    assert saved[0].reference == data.reference
    assert saved[0].total == 20000


@pytest.mark.parametrize("reverse_insert", [False, True], ids=["insert_A_then_B", "insert_B_then_A"])
def test_rental_selection(sut, reverse_insert):
    equipment = new_equipment(sut)
    prefix = uuid4().hex[:8]
    references = [prefix + "-A", prefix + "-B"]
    for reference in (reversed(references) if reverse_insert else references):  # порядок вставки не має значення
        sut.service.rent(RentalRequest(reference, equipment.id, 1, 2, False))
    actual = [row[0] for row in sut.db.execute(
        "SELECT r.reference FROM rentals r JOIN rental_items i ON i.rental_id=r.id "
        "WHERE i.equipment_id=%s ORDER BY r.reference", (equipment.id,))]  # явне сортування замість "як повернула БД"
    assert actual == references


def test_policy_rejection(sut):
    class DeniedPolicy:
        def is_allowed(self, equipment, quantity, days):
            return False

    equipment = new_equipment(sut)
    denied = RentalService(sut.equipment, sut.rentals, DeniedPolicy())
    with pytest.raises(RentalRejectedError):
        denied.rent(new_request(equipment))
    assert sut.rentals.find_rentals(equipment.id, S.ACTIVE) == []


def test_repeated_return(sut):
    saved = sut.service.rent(new_request(new_equipment(sut)))
    returned = sut.service.return_rental(saved.id, 0)
    with pytest.raises(RentalRejectedError):
        sut.service.return_rental(saved.id, 0)
    assert sut.rentals.find_by_id(saved.id) == returned
