import logging
import re
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

_MASHREQ_DATE = re.compile(r'^\d{2}/\d{2}/\d{4}(?:\s|$)')
_MASHREQ_ENTRY = re.compile(
    r'^(?P<day>\d{2}/\d{2}/\d{4}) (?:VALUE DATE: \S+ )?(?P<kind>.+?) (?P<ref>\S+) (?P<debit>[\d,]+\.\d{3}) '
    r'(?P<credit>[\d,]+\.\d{3}) (?P<balance>[\d,]+\.\d{3})(?P<extra>.*)$')
_MASHREQ_FROM_TO = re.compile(r'FROM ACCOUNT No:\s*(\d{6,})\s+TO\s+ACCOUNT No:\s*(\d{6,})')
_IBAN_ACCOUNT = re.compile(r'AE\d{2}\d{3}(\d{16})')
_MASHREQ_ACCOUNT_VALUE = re.compile(r'^(\d{9,})\s+AED\b')
_MASHREQ_TRANSFERS = ('Account to Account', 'IPP TRANSFER', 'Online Local Fund Transfer', 'Instant Card Payment')
_ENBD_START = re.compile(r'^(\d{2}[A-Z]{3}\d{2}) (.+)$')
_ENBD_AMOUNTS = re.compile(r'([\d,]+\.\d{2}) ([\d,]+\.\d{2})(Cr)?$')
_ENBD_ACCOUNT = re.compile(r'CURRENT ACCOUNT\s*\n\s*(\d{10,})')
_ENBD_TRANSFERS = ('TELEGRAPHIC TRF', 'BANKNET TRANSFER', 'IPP CUSTOMER CREDIT', 'INWARD REMITTANCE')


class StatementLine(BaseModel):
    model_config = ConfigDict(extra='forbid')

    bank: str
    last4: str
    day: date
    kind: str
    amount: float
    counterparty_name: str = ''
    counterparty_account: str = ''

    @property
    def is_inflow(self) -> bool:
        return self.amount < 0


def read_pdf_text(path: Path) -> str:
    from pypdf import PdfReader
    logging.getLogger('pypdf').setLevel(logging.ERROR)
    return '\n'.join(page.extract_text() or '' for page in PdfReader(path).pages)


def _number(text: str) -> float:
    return float(text.replace(',', ''))


def parse_mashreq(text: str) -> list[StatementLine]:
    lines: list[StatementLine] = []
    first = re.search(r'Account (\d{12}) AED', text)
    own = first.group(1) if first else ''
    rows = [raw.strip() for raw in text.splitlines()]
    entry: list[str] = []

    def flush():
        parsed = _MASHREQ_ENTRY.match(' '.join(entry))
        if parsed and parsed.group('kind').startswith(_MASHREQ_TRANSFERS):
            amount = _number(parsed.group('debit')) - _number(parsed.group('credit'))
            if amount:
                lines.append(_mashreq_line({'day': datetime.strptime(parsed.group('day'), '%d/%m/%Y').date(),
                                            'kind': parsed.group('kind').strip(), 'amount': amount,
                                            'extra': parsed.group('extra')}, own))

    for previous, row in zip([''] + rows, rows):
        account = _MASHREQ_ACCOUNT_VALUE.match(row)
        if previous == 'Account No' and account:
            own = account.group(1)
        if _MASHREQ_DATE.match(row):
            flush()
            entry = [row]
        elif entry:
            entry.append(row)
    flush()
    return lines


def _mashreq_line(entry: dict, own: str) -> StatementLine:
    kind, extra = entry['kind'], entry['extra']
    details = kind + ' ' + extra
    direct = _MASHREQ_FROM_TO.search(details)
    if direct:
        sender, receiver = direct.groups()
        own, other = (sender, receiver) if entry['amount'] > 0 else (receiver, sender)
        accounts = [other]
    else:
        ibans = [account.lstrip('0') for account in _IBAN_ACCOUNT.findall(details) if not own or not account.endswith(own)]
        accounts = ibans or [a for a in re.findall(r'(?:A/C ?No:|IPP TRANSFER)\s*(\d{6,})', details) if a != own]
    named = re.match(r'Online Local Fund Transfer, (.+?), A/C', kind)
    name = _spaced_name(named.group(1)) if named else ''
    kind_name = re.sub(r'\s+', ' ', re.sub(r'AccountTransfer', 'Account Transfer', kind.split(',')[0])).strip()
    kind_name = re.sub(r' \d{6,}.*$', '', kind_name)
    return StatementLine(bank='Mashreq', last4=own[-4:], day=entry['day'], kind=kind_name,
                         amount=entry['amount'], counterparty_name=name,
                         counterparty_account=accounts[0] if accounts else '')


def _spaced_name(text: str) -> str:
    return ' '.join(re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', text).split())


def parse_enbd(text: str) -> list[StatementLine]:
    account = _ENBD_ACCOUNT.search(text)
    own = account.group(1)[-4:] if account else ''
    lines: list[StatementLine] = []
    balance = None
    current: dict | None = None
    for raw in text.splitlines():
        row = raw.strip()
        start = _ENBD_START.match(row)
        if start and 'BROUGHT FORWARD' in row:
            amounts = _ENBD_AMOUNTS.search(row) or re.search(r'([\d,]+\.\d{2})(Cr)?$', row)
            if amounts:
                balance = _number(amounts.groups()[-2] if len(amounts.groups()) == 3 else amounts.group(1))
            current = None
            continue
        if start:
            current = {'day': datetime.strptime(start.group(1).title(), '%d%b%y').date(), 'kind': start.group(2).strip(), 'extra': ''}
        elif current is not None:
            current['extra'] += ' ' + row
        amounts = _ENBD_AMOUNTS.search(row)
        if current is not None and amounts:
            amount, after = _number(amounts.group(1)), _number(amounts.group(2))
            if amounts.group(3) is None:
                after = -after
            outflow = balance is None or after < balance
            if current['kind'].startswith(_ENBD_TRANSFERS):
                iban = re.search(r'AE\d{2}[\dX-]{6,}', current['extra'])
                digits = re.sub(r'\D', '', iban.group(0).split('XXXX-')[-1]) if iban else ''
                lines.append(StatementLine(bank='ENBD', last4=own, day=current['day'], kind=current['kind'],
                                           amount=amount if outflow else -amount, counterparty_account=digits))
            balance = after
            current = None
    return lines


def parse(path: Path) -> list[StatementLine]:
    text = read_pdf_text(path)
    return parse_enbd(text) if 'CURRENT ACCOUNT' in text and 'BROUGHT FORWARD' in text else parse_mashreq(text)
