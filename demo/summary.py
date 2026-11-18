"""Локальная демонстрация правил. Python 3.10+, без сети и сторонних пакетов."""
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


def timestamp(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('Нужен часовой пояс')
    return result


def classify(case, now):
    """Чат не подтверждает операции и не меняет решение правил."""
    def decision(priority, state, reason):
        return {'id': case['id'], 'priority': priority, 'state': state, 'reason': reason}

    def review(reason):
        return decision(1, 'Проверить данные', reason)

    crm = case.get('crm', {})
    try:
        kind = case.get('kind')
        if kind == 'delivery':
            status = crm['status']
            if status == 'Принято':
                received = timestamp(crm['received_at'])
                if received > now:
                    return review('Приёмка датирована будущим; проверить запись CRM.')
                return decision(3, 'Без вмешательства', 'Приёмка подтверждена в CRM.')
            if status != 'В пути':
                return review('Неизвестный статус поставки; проверить вручную.')
            if crm.get('received_at') is not None:
                return review('Статус «В пути» противоречит отметке приёмки.')
            due = timestamp(crm['due_at'])
            if now >= due:
                reason = ('Срок доставки наступил, приёмка в CRM не подтверждена.'
                          if now == due else 'Срок доставки прошёл, приёмка в CRM не подтверждена.')
                return decision(1, 'Проверить сейчас', reason)
            if due.astimezone(now.tzinfo).date() == now.date():
                return decision(2, 'Контроль сегодня', 'Доставка запланирована сегодня, срок ещё не наступил.')
            return decision(3, 'Плановый контроль', 'Срок доставки ещё не наступил.')

        if kind in {'onboarding', 'offboarding'}:
            day_key, flag = (('first_day', 'documents_confirmed') if kind == 'onboarding'
                             else ('last_day', 'manager_confirmed'))
            day = date.fromisoformat(crm[day_key])
            confirmed = crm[flag]
            if type(confirmed) is not bool:
                return review('Подтверждение должно быть явно true или false.')
            if confirmed:
                return decision(3, 'Без вмешательства', 'Необходимое подтверждение есть в CRM.')
            if day <= now.date():
                return decision(1, 'Проверить сегодня', 'Событие сегодня или ранее, обязательного подтверждения в CRM нет.')
            if day == now.date() + timedelta(days=1):
                return decision(2, 'Подготовить сегодня', 'Событие завтра, обязательного подтверждения в CRM нет.')
            return decision(3, 'Плановый контроль', 'Подтверждение отсутствует, событие позже завтрашнего дня.')
        return review('Неизвестный тип операции; проверить вручную.')
    except (KeyError, TypeError, ValueError):
        return review('Не хватает корректных полей CRM; проверить источник, не считать случай завершённым.')


def build_summary(payload):
    now = timestamp(payload['as_of'])
    cases = payload['cases']
    ids = [case['id'] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError('Повторяющийся ID: сначала устраните неоднозначность связывания.')
    results = []
    for case in cases:
        result = classify(case, now)
        # Сохраняем данные источников отдельно от выводов правил.
        result.update(kind=case.get('kind'), crm=case.get('crm', {}), crm_text=case.get('crm_text', ''),
                      messages=case.get('messages', []))
        results.append(result)
    # Внутри одинакового уровня сохраняем порядок входа; окончательную очередь выбирает сотрудник.
    return {'as_of': payload['as_of'], 'cases': sorted(results, key=lambda row: row['priority'])}


if __name__ == '__main__':
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name('cases.json')
    print(json.dumps(build_summary(json.loads(path.read_text(encoding='utf-8'))), ensure_ascii=False, indent=2))
