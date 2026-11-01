from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from pkg.model.base import Model


class Checklist(Model):
    class Item(BaseModel):
        model_config = ConfigDict(extra='forbid')

        name: str
        icon: str = ''

    class Section(BaseModel):
        model_config = ConfigDict(extra='forbid')

        name: str
        items: list['Checklist.Item']

    SUBDIR: ClassVar[str] = 'checklists'

    key: str
    name: str
    icon: str = ''
    order: int = 0
    sections: list[Section]
