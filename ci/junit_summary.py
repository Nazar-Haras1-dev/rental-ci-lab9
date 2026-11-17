"""Перетворює JUnit XML (test report) на читабельну таблицю Markdown.
У GitHub Actions таблицю дописуємо у $GITHUB_STEP_SUMMARY, тож вона видна на сторінці запуску без завантаження файлів.
Використання: python ci/junit_summary.py <назва етапу> reports/unit.xml [ще файли...]
Скрипт лише показує результат і НІКОЛИ не змінює статус етапу: падіння тестів фіксує сам pytest."""
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def read_report(path):
    """Повертає (кількість тестів, помилок-assert, помилок-exception, пропущено, секунд, список невдалих)."""
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    tests = failures = errors = skipped = 0
    seconds = 0.0
    failed = []
    for suite in suites:
        tests += int(suite.get("tests", 0))
        failures += int(suite.get("failures", 0))
        errors += int(suite.get("errors", 0))
        skipped += int(suite.get("skipped", 0))
        seconds += float(suite.get("time", 0))
        for case in suite.findall("testcase"):
            problem = case.find("failure")
            kind = "FAILED"
            if problem is None:
                problem = case.find("error")
                kind = "ERROR"
            if problem is not None:
                message = (problem.get("message") or "").strip().splitlines()
                failed.append((kind, f"{case.get('classname', '')}::{case.get('name', '')}", message[0] if message else ""))
    return tests, failures, errors, skipped, seconds, failed


def main(title, files):
    lines = [f"### {title}", ""]
    total_problems = 0
    for file in files:
        if not Path(file).exists():
            lines.append(f"**{file}**: файл звіту не створено (етап міг упасти ще до запуску тестів).")
            continue
        tests, failures, errors, skipped, seconds, failed = read_report(file)
        passed = tests - failures - errors - skipped
        total_problems += failures + errors
        lines += ["| Файл звіту | Усього | Пройшло | Failed | Error | Skipped | Час, с |",
                  "|---|---|---|---|---|---|---|",
                  f"| `{file}` | {tests} | {passed} | {failures} | {errors} | {skipped} | {seconds:.2f} |", ""]
        if failed:
            lines += ["**Невдалі тести:**", ""]
            lines += [f"- `{kind}` `{name}`: {message}" for kind, name, message in failed]
            lines.append("")
    lines.append("Результат: **є невдалі тести**" if total_problems else "Результат: **усі тести пройшли**")
    text = "\n".join(lines) + "\n"
    target = os.getenv("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as summary:
            summary.write(text)
    print(text)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("Використання: python ci/junit_summary.py <назва етапу> <junit.xml> [...]")
    main(sys.argv[1], sys.argv[2:])
