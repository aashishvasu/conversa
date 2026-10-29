"""Model-callable random number generation, sampling, and shuffling."""

import random
import secrets
from typing import Literal

from pydantic import Field, model_validator

from .conversa_tool import ConversaTool, ToolArguments, ToolOutput

MAX_COUNT = 1000
MAX_ITEMS = 1000
MAX_RANGE_BOUND = 1_000_000_000_000


class RandomArguments(ToolArguments):
    action: Literal["integers", "sample", "shuffle"] = Field(description="Use 'sample' to choose items, 'shuffle' to reorder items, and 'integers' for dice, rolls, and random numbers.")
    start: int = Field(default=1, ge=-MAX_RANGE_BOUND, le=MAX_RANGE_BOUND, description="Inclusive lower bound for action='integers'.")
    end: int | None = Field(default=None, ge=-MAX_RANGE_BOUND, le=MAX_RANGE_BOUND, description="Inclusive upper bound for action='integers'.")
    count: int = Field(default=1, ge=1, le=MAX_COUNT, description="How many integers or sampled items to return.")
    items: list[str | int | float] | None = Field(default=None, min_length=1, max_length=MAX_ITEMS, description="Items to sample from or shuffle for action='sample' or action='shuffle'.")
    replacement: bool = Field(default=False, description="For action='sample', true allows the same item to be picked more than once.")
    seed: int | None = Field(default=None, description="Optional integer seed for reproducible random results. Leave null for real randomness.")

    @model_validator(mode="after")
    def validate_action_fields(self) -> "RandomArguments":
        if self.action == "integers":
            if self.end is None:
                raise ValueError("action 'integers' requires 'end'")
            if self.items is not None:
                raise ValueError("action 'integers' does not accept 'items'")
            if self.replacement:
                raise ValueError("action 'integers' does not accept 'replacement'")
            if self.start > self.end:
                raise ValueError(f"start ({self.start}) must be <= end ({self.end})")

        elif self.action == "sample":
            if self.items is None:
                raise ValueError("action 'sample' requires 'items'")
            if self.end is not None:
                raise ValueError("action 'sample' does not accept 'end'")
            if not self.replacement and self.count > len(self.items):
                raise ValueError(f"cannot sample {self.count} items without replacement from {len(self.items)} items")

        elif self.action == "shuffle":
            if self.items is None:
                raise ValueError("action 'shuffle' requires 'items'")
            if self.end is not None:
                raise ValueError("action 'shuffle' does not accept 'end'")
            if self.count != 1:
                raise ValueError("action 'shuffle' does not accept 'count'")
            if self.replacement:
                raise ValueError("action 'shuffle' does not accept 'replacement'")

        return self


async def execute_random(arguments: ToolArguments) -> ToolOutput:
    assert isinstance(arguments, RandomArguments)
    if arguments.seed is not None:
        rng = random.Random(arguments.seed)
        seeded = True
    else:
        rng = secrets.SystemRandom()
        seeded = False

    if arguments.action == "integers":
        assert arguments.end is not None
        results = [rng.randint(arguments.start, arguments.end) for _ in range(arguments.count)]
        val = {
            "results": results,
            "count": arguments.count,
            "start": arguments.start,
            "end": arguments.end,
            "seeded": seeded,
        }
        trace = {"action": "integers", "count": arguments.count, "seeded": seeded}
        return ToolOutput(val, trace)

    if arguments.action == "sample":
        assert arguments.items is not None
        items_copy = list(arguments.items)
        if arguments.replacement:
            results = rng.choices(items_copy, k=arguments.count)
        else:
            results = rng.sample(items_copy, k=arguments.count)
        val = {
            "results": results,
            "count": arguments.count,
            "replacement": arguments.replacement,
            "seeded": seeded,
        }
        trace = {"action": "sample", "count": arguments.count, "replacement": arguments.replacement, "seeded": seeded}
        return ToolOutput(val, trace)

    assert arguments.items is not None
    shuffled = list(arguments.items)
    rng.shuffle(shuffled)
    val = {
        "shuffled": shuffled,
        "count": len(shuffled),
        "seeded": seeded,
    }
    trace = {"action": "shuffle", "count": len(shuffled), "seeded": seeded}
    return ToolOutput(val, trace)


RANDOM_TOOL = ConversaTool(
    name="random",
    description=(
        "Use this when the user asks for a random choice, chance outcome, winner, sample, shuffle, draw, dice roll, coin-style decision, or random number. "
        "Prefer sample when choosing from user-provided options, shuffle when reordering options, and integers only when a numeric range, die, roll, or count is requested. "
        "Use seed only when the user asks for repeatable or reproducible randomness."
    ),
    arguments=RandomArguments,
    execute=execute_random,
    artifact_fresh_for=None,
)
