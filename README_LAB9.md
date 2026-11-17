# Лаба 9. CI/CD: GitHub Actions для SUT B «Прокат обладнання» (варіант 03)

## 1. Що ми робимо і навіщо (простими словами)

**CI (Continuous Integration)** – це «робот-перевіряльник». Щойно ви робите `git push`, GitHub сам:
1. бере вашу свіжу версію коду на чистій віртуальній машині (runner),
2. ставить залежності,
3. піднімає PostgreSQL,
4. запускає всі тести,
5. показує зелену ✅ або червону ❌ позначку, звіти й логи.

Навіщо: щоб «у мене на ноутбуці працює» не було аргументом. Перевірка відбувається в чистому середовищі й однаково для всіх.

Що саме у нас перевіряється (усе вже написано в лабах 3–8, тут лише автоматичний запуск):

| Job | Що робить | Потрібна БД | Тестів |
|---|---|---|---|
| `build` | ставить залежності, перевіряє, що код імпортується | ні | – |
| `unit` | unit-тести сервісу (mock-и) + перевірка середовища | ні | 41 |
| `integration` | Repository↔БД, Service→Repository→БД | так | 61 |
| `api` | REST API (FastAPI) проти реальної БД | так | 35 |
| `regression` | smoke (4) і повний regression (11) | так | 4 + 11 |

Порядок: `build` → `unit` → (`integration`, `api`, `regression` паралельно). Якщо unit червоний, дорогі job-и з БД навіть не стартують (це й є `needs`).

## 2. Склад проєкту (що де лежить)

```
sut-b/
├── .github/workflows/ci.yml     ← САМ PIPELINE (головний файл лаби)
├── ci/
│   ├── apply_migration.py       ← чекає на БД і накочує міграцію в CI
│   └── junit_summary.py         ← робить таблицю результатів у Job Summary
├── ci_demo/
│   ├── break_service.patch      ← демо: ламає знижку 15% → 10% (pipeline стає червоним)
│   └── test_intentional_failure.py ← альтернативне демо: один навмисний червоний тест
├── requirements-ci.txt          ← залежності для CI (без Docker/testcontainers)
├── pytest.ini                   ← маркери smoke/regression, testpaths = tests
├── .gitignore                   ← не комітимо .venv, __pycache__, reports/
├── rental/  migrations/  pyproject.toml   ← офіційний SUT B
└── tests/
    ├── test_service_unit.py, test_environment.py   ← unit
    ├── integration/   ← лаба 4 (без навмисно падаючого тесту)
    ├── rest_api/      ← лаба 6
    └── regression/    ← лаба 8
```

Навмисно падаючий тест лаби 4 сюди **не** включено: у CI мають бути зелені тести, а «червоний» ми показуємо окремо й керовано (розділ 7).

## 3. Крок за кроком: репозиторій на GitHub (macOS)

1. На github.com → **New repository** → ім'я, наприклад `rental-ci-lab9`, **Private/Public** на вибір, **без** README (порожній).
2. У терміналі:
```bash
cd ~/Desktop/тестування/lab9/sut-b
git init
git branch -M main
git add .
git commit -m "Lab 9: CI pipeline"
git remote add origin https://github.com/<ваш-логін>/rental-ci-lab9.git
git push -u origin main
```
   Якщо git просить пароль, GitHub більше не приймає звичайний пароль: потрібен **Personal Access Token** (Settings → Developer settings → Tokens) або `gh auth login`.
3. Відкрийте репозиторій → вкладка **Actions**. Там вже йде запуск **CI** (бо ми зробили push у `main`).

## 4. Пояснення `ci.yml` по блоках

```yaml
name: CI
```
Назва, яку видно у вкладці Actions.

```yaml
on:
  push:
    branches: [main]
  pull_request:
  workflow_dispatch:
```
**Тригери** (trigger): коли запускати. `push` у main; будь-який pull request; `workflow_dispatch` – кнопка «Run workflow» вручну.

```yaml
permissions:
  contents: read
```
Принцип мінімальних прав: pipeline лише читає код.

```yaml
env:
  PYTHON_VERSION: "3.12"
  DB_HOST: 127.0.0.1 ...
```
Змінні для всіх job-ів. Наш код (`rental/database.py`) читає саме `DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD`, тому нічого в коді міняти не треба. Ім'я БД містить `test`, бо тести інтеграції відмовляються працювати з БД без слова `test` (захист від стирання «справжніх» даних).

### Job `build`
- `runs-on: ubuntu-latest` – віртуальна машина (runner).
- `actions/checkout` – завантажує код репозиторію на runner.
- `actions/setup-python` + `cache: pip` – ставить Python 3.12 і кешує pip, щоб наступні запуски були швидші.
- `pip install -r requirements-ci.txt` – залежності.
- `python -c "import rental.service, rental.api"` – швидка перевірка, що застосунок збирається/імпортується.

### Job `unit`
- `needs: build` – стартує лише після успішного build.
- `pytest ... --junitxml=reports/unit.xml` – запускає тести й **пише звіт у форматі JUnit XML** (стандартний формат, який розуміють CI-системи).
- Крок `if: always()` – виконується **навіть якщо тести впали**; саме тому звіт і Job Summary з'являються і на червоному запуску.
- `upload-artifact` – зберігає `reports/unit.xml` як **артефакт**: файл-результат запуску, його можна завантажити зі сторінки запуску.

### Jobs `integration`, `api`, `regression`
Мають блок **`services: postgres`**:
```yaml
services:
  postgres:
    image: postgres:17
    env: {POSTGRES_USER: rental_student, POSTGRES_PASSWORD: student, POSTGRES_DB: rental_variant03_test}
    ports: ["5432:5432"]
    options: --health-cmd "pg_isready ..." --health-interval 5s ...
```
GitHub сам запускає контейнер PostgreSQL поруч із job-ом. `ports` виставляє його на `127.0.0.1:5432` runner-а (саме це ми прописали в `DB_HOST/DB_PORT`). `health-*` – контейнер вважається готовим, коли `pg_isready` відповідає «ок»; job не стартує раніше. (Docker на вашому Mac при цьому не потрібен: контейнер крутиться в хмарі GitHub.)

Далі:
- `python ci/apply_migration.py` – накочує `migrations/V1__create_tables.sql` (ще й чекає до 60 с, поки БД прокинеться).
- `pytest tests/integration | tests/rest_api | tests/regression -m smoke / -m regression` – відповідні набори. У `regression` змінна `REGRESSION_DB: local` каже фікстурі брати БД із service-контейнера, а не підіймати Testcontainers (Docker-in-Docker не потрібен).
- `python ci/junit_summary.py` – друкує таблицю у **Job Summary** (`$GITHUB_STEP_SUMMARY`).

## 5. Що має вийти (очікуваний результат)

На сторінці успішного запуску:
- 5 зелених job-ів: build, unit, integration, api, regression (граф залежностей: build → unit → три паралельні).
- Внизу – блок **Artifacts**: `junit-unit`, `junit-integration`, `junit-api`, `junit-regression`.
- На вкладці Summary – таблиці: unit 41, integration 61, api 35, smoke 4, regression 11; «усі тести пройшли».

Локальна перевірка, яку я виконав перед видачею (на PostgreSQL 16, ті самі команди, що в ci.yml): unit 41 passed; integration 61 passed; api 35 passed; smoke 4 passed; regression 11 passed; ci_demo патч дає 6 червоних unit-тестів.
**Чесно:** сам GitHub Actions у моєму середовищі запустити неможливо, тому YAML перевірено на валідність синтаксису, а кроки – локальним відтворенням. Перший реальний запуск зробите ви; якщо щось відрізнятиметься – надішліть лог, виправимо.

## 6. Як читати pipeline (для захисту)

1. **Actions → клік на запуск** → бачите граф jobs. Клік на job → список кроків; клік на крок → лог.
2. Червоний крок розгорніть: там текст помилки pytest (який тест, який assert, очікувалось/отримано).
3. **Summary** (вкладка запуску) – наша таблиця. **Artifacts** (унизу) – JUnit XML; можна завантажити й відкрити.
4. Кнопка **Re-run jobs** перезапускає без нового коміту.

## 7. Демонстрація «червоного» pipeline (обов'язково показати)

**Варіант А (змінюємо бізнес-код – показує, що CI ловить регресію):**
```bash
git checkout -b break-discount
patch -p1 < ci_demo/break_service.patch      # у service.py знижка 15 → 10
git commit -am "demo: break discount" && git push -u origin break-discount
```
Створіть Pull Request на main → job `unit` червоний (6 тестів падають, наприклад `test_calculate_total_boundary_exact_days`), `integration/api/regression` **не стартують** (`needs`). У Summary видно назви невдалих тестів.
Виправлення: `git revert HEAD` (або `git checkout main -- rental/service.py`), push → знову зелений.

**Варіант Б (без змін коду):**
`cp ci_demo/test_intentional_failure.py tests/`, commit, push → unit червоний на одному тесті; після `git rm tests/test_intentional_failure.py` – зелений.

## 8. Чекліст (що перевірити → як → правильний результат)

| # | Перевірка | Як | Правильно |
|---|---|---|---|
| 1 | Pipeline запускається автоматично | зробити push | запуск з'являється в Actions |
| 2 | Є етапи build/test/… | відкрити граф | 5 jobs, залежності стрілками |
| 3 | PostgreSQL піднято в CI | лог кроку «Initialize containers» | видно контейнер postgres:17 + health «healthy» |
| 4 | Міграція застосована | лог «Застосувати міграцію» | «Міграцію застосовано. Таблиці: equipment, rental_items, rentals» |
| 5 | Тести без Docker локально | – | CI не вимагає Docker на вашому Mac |
| 6 | JUnit-звіти збережено | Artifacts | 4 артефакти |
| 7 | Summary з результатами | вкладка Summary | таблиці з числами |
| 8 | Зелений запуск | – | усе ✅ |
| 9 | Червоний запуск | розділ 7 | ❌ у unit, пізніші jobs skipped |
| 10 | Відновлення | revert | знову ✅ |
| 11 | Немає `continue-on-error` | пошук у ci.yml | відсутнє: падіння тестів реально ламає pipeline |

## 9. Сценарій захисту (говоріть так)

1. «Pipeline описаний у `.github/workflows/ci.yml`, запускається на push і PR.»
2. «Є 5 job-ів; unit запускається першим, бо він швидкий і без БД; важчі – лише якщо він зелений.»
3. «PostgreSQL у CI – це service container, з healthcheck; параметри передаю змінними `DB_*`, код не змінював.»
4. «Міграція застосовується скриптом `ci/apply_migration.py`, який чекає готовності БД.»
5. «Кожен job пише JUnit XML і завантажує як артефакт; таблицю результатів бачимо в Job Summary.»
6. «Кроки зі звітами мають `if: always()`, щоб звіт був і при падінні.»
7. [показати зелений запуск]
8. [показати червоний: розділ 7 → що саме впало → виправили → зелений]

## 10. Глосарій

- **CI** – автоматична збірка й перевірка при кожній зміні коду.
- **Workflow** – один YAML-файл у `.github/workflows`, опис автоматизації.
- **Trigger (`on`)** – подія, що запускає workflow.
- **Job** – набір кроків на одному runner-і; jobs можуть йти паралельно або по `needs`.
- **Step** – окрема дія/команда всередині job.
- **Runner** – віртуальна машина, де це виконується (`ubuntu-latest`).
- **Action (`uses:`)** – готовий перевикористовуваний крок (checkout, setup-python…).
- **Service container** – допоміжний контейнер (тут PostgreSQL) на час job-а.
- **Artifact** – файл-результат запуску, який зберігається й завантажується.
- **JUnit XML** – стандартний формат звіту про тести.
- **Job Summary** – Markdown-звіт на сторінці запуску (`$GITHUB_STEP_SUMMARY`).
- **`if: always()`** – виконати крок незалежно від успіху попередніх.
- **Pipeline** – весь ланцюжок jobs від коміту до результату.
