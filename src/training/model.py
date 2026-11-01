from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from pkg.model.base import Model


class Exercise(Model):
    SUBDIR: ClassVar[str] = 'training/exercises'

    key: str
    name: str
    equipment: str
    start_kg: float
    step_kg: float
    min_reps: int
    max_reps: int
    images: list[str] = []
    video: str = ''
    cues: list[str] = []


class Workout(Model):
    SUBDIR: ClassVar[str] = 'training/workouts'

    key: str
    name: str
    order: int
    pairs: list[list[str]]


class Guide(Model):
    class Warmup(BaseModel):
        model_config = ConfigDict(extra='forbid')

        name: str
        amount: str
        images: list[str] = []

    SUBDIR: ClassVar[str] = 'training/guide'

    key: str = 'guide'
    sets: int
    push_seconds: int
    lower_seconds: int
    switch_seconds: int
    rest_seconds: int
    before_gym: list[str] = []
    warmup: list[Warmup] = []
    rules: list[str] = []


class Session(Model):
    class Set(BaseModel):
        model_config = ConfigDict(extra='forbid')

        exercise: str
        number: int
        kg: float
        reps: int

    SUBDIR: ClassVar[str] = 'training/sessions'

    key: str
    workout: str
    sets: list[Set] = []

    def sets_of(self, exercise: str) -> list[Set]:
        return sorted((s for s in self.sets if s.exercise == exercise), key=lambda s: s.number)
