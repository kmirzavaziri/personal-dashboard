import logging
import re
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

_MASHREQ_LINE = re.compile(
    r'^(\d{2}/\d{2}/\d{4}) (?:VALUE DATE: \S+ )?(.+?) (\S+) ([\d,]+\.\d{3}) ([\d,]+\.\d{3}) ([\d,]+\.\d{3})$')
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
    current: dict | None = None

    def flush():
        if current and current['kind'].startswith(_MASHREQ_TRANSFERS):
            lines.append(_mashreq_line(current, own))

    previous = ''
    for raw in text.splitlines():
        account = _MASHREQ_ACCOUNT_VALUE.match(raw.strip())
        if previous == 'Account No' and account:
            own = account.group(1)
        previous = raw.strip()
        match = _MASHREQ_LINE.match(raw.strip())
        if match:
            flush()
            day, kind, _, debit, credit, _ = match.groups()
            current = {'day': datetime.strptime(day, '%d/%m/%Y').date(), 'kind': kind.strip(),
                       'amount': _number(debit) - _number(credit), 'extra': ''}
        elif current is not None:
            current['extra'] += ' ' + raw.strip()
    flush()
    return [line for line in lines if line.amount]


def _mashreq_line(entry: dict, own: str) -> StatementLine:
    kind, extra = entry['kind'], entry['extra']
    accounts = [a for a in re.findall(r'(?:ACCOUNT No:|A/C ?No:|IPP TRANSFER)\s*(\d{6,})', kind + ' ' + extra) if a != own]
    name = ''
    named = re.match(r'Online Local Fund Transfer, (.+?), A/C', kind)
    if named:
        name = ' '.join(named.group(1).split())
    kind_name = re.sub(r'\s+', ' ', re.sub(r'AccountTransfer', 'Account Transfer', kind.split(',')[0])).strip()
    kind_name = re.sub(r' \d{6,}$', '', kind_name)
    return StatementLine(bank='Mashreq', last4=own[-4:], day=entry['day'], kind=kind_name,
                         amount=entry['amount'], counterparty_name=name,
                         counterparty_account=accounts[0] if accounts else '')


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
