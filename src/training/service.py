from dataclasses import dataclass
from datetime import date, datetime, timezone

from training.model import Exercise, Guide, Session, Workout
from transactions.rules import Clock


@dataclass
class Slot:
    exercise: Exercise
    kg: float
    last: list[Session.Set]
    done: list[Session.Set]


@dataclass
class Plan:
    day: date
    guide: Guide
    workout: Workout
    pairs: list[list[Slot]]


def today(config) -> date:
    return Clock.load(config.db).local(datetime.now(timezone.utc)).date()


def plan(config) -> Plan:
    day = today(config)
    guide = Guide.objects.get(key='guide')
    exercises = {exercise.key: exercise for exercise in Exercise.objects.all()}
    current = Session.objects.get_or_none(key=day.isoformat())
    earlier = [session for session in _sessions() if session.key < day.isoformat()]
    workout = _workout(current, earlier)
    pairs = [[_slot(exercises[key], guide, earlier, current) for key in pair] for pair in workout.pairs]
    return Plan(day=day, guide=guide, workout=workout, pairs=pairs)


def record_set(config, workout: str, exercise: str, number: int, kg: float, reps: int) -> Session:
    day = today(config).isoformat()
    if Exercise.objects.get_or_none(key=exercise) is None or Workout.objects.get_or_none(key=workout) is None:
        raise ValueError(f'unknown exercise or workout: {exercise}, {workout}')
    session = Session.objects.get_or_none(key=day) or Session(key=day, workout=workout)
    session.sets = [s for s in session.sets if not (s.exercise == exercise and s.number == number)]
    session.sets.append(Session.Set(exercise=exercise, number=number, kg=kg, reps=reps))
    session.save()
    return session


def restart(config) -> None:
    session = Session.objects.get_or_none(key=today(config).isoformat())
    if session is not None:
        session.delete()


def _sessions() -> list[Session]:
    return sorted(Session.objects.all(), key=lambda session: session.key)


def _workout(current: Session | None, earlier: list[Session]) -> Workout:
    workouts = sorted(Workout.objects.all(), key=lambda workout: workout.order)
    if current is not None:
        return next(workout for workout in workouts if workout.key == current.workout)
    if not earlier:
        return workouts[0]
    keys = [workout.key for workout in workouts]
    return workouts[(keys.index(earlier[-1].workout) + 1) % len(workouts)]


def _slot(exercise: Exercise, guide: Guide, earlier: list[Session], current: Session | None) -> Slot:
    last = next((session.sets_of(exercise.key) for session in reversed(earlier) if session.sets_of(exercise.key)), [])
    return Slot(exercise=exercise, kg=_next_kg(exercise, guide, last), last=last,
                done=current.sets_of(exercise.key) if current else [])


def _next_kg(exercise: Exercise, guide: Guide, last: list[Session.Set]) -> float:
    if not last:
        return exercise.start_kg
    kg = last[0].kg
    if len(last) >= guide.sets and all(s.reps >= exercise.max_reps for s in last):
        return kg + exercise.step_kg
    if last[0].reps < exercise.min_reps:
        return max(kg - exercise.step_kg, exercise.step_kg)
    return kg
