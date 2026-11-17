"""Демонстрація «червоного» CI без зміни бізнес-коду (варіант Б).
Скопіюйте файл у tests/ (cp ci_demo/test_intentional_failure.py tests/) і зробіть push: unit-job стане червоним.
Після демонстрації видаліть файл з tests/ і зробіть новий commit: pipeline знову зелений."""


def test_demo_ci_must_turn_red(rental_service):
    # premium, 5 днів, 1000 коп * 1 шт: 5000 - 15% = 4250. Навмисно очікуємо 5000, щоб показати падіння в CI.
    assert rental_service.calculate_total(1000, 1, 5, premium=True) == 5000
