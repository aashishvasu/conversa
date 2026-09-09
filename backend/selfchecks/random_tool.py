"""Selfcheck: python -m selfchecks.random_tool"""

import asyncio
import json

from tools import RANDOM_TOOL
from tools.conversa_tool import ToolCall, execute_tool


def run(call_id, arguments):
    return asyncio.run(execute_tool(RANDOM_TOOL, ToolCall(call_id, "random", arguments)))


# integers: inclusive range and count
rng_int = run("r-1", {"action": "integers", "start": 1, "end": 6, "count": 10})
assert rng_int.error is None, rng_int
data_int = json.loads(rng_int.content)
assert len(data_int["results"]) == 10 and all(1 <= x <= 6 for x in data_int["results"]), data_int
assert data_int["seeded"] is False, data_int

# seeded calls are reproducible
seed1 = run("r-2", {"action": "integers", "start": 1, "end": 100, "count": 5, "seed": 42})
seed2 = run("r-3", {"action": "integers", "start": 1, "end": 100, "count": 5, "seed": 42})
assert json.loads(seed1.content)["results"] == json.loads(seed2.content)["results"]
assert json.loads(seed1.content)["seeded"] is True

bad_range = run("r-4", {"action": "integers", "start": 10, "end": 5})
assert bad_range.error == "invalid_arguments", bad_range

# Field owns the unconditional bounds; oversized generated input fails validation
end_out_of_range = run("r-19", {"action": "integers", "start": 1, "end": 10**13})
assert end_out_of_range.error == "invalid_arguments", end_out_of_range

count_below_one = run("r-20", {"action": "integers", "start": 1, "end": 6, "count": 0})
assert count_below_one.error == "invalid_arguments", count_below_one

seed_out_of_bounds = run("r-21", {"action": "integers", "start": 1, "end": 6, "seed": 2**63})
assert seed_out_of_bounds.error == "invalid_arguments", seed_out_of_bounds

items_too_long = run("r-22", {"action": "shuffle", "items": [0] * 1001})
assert items_too_long.error == "invalid_arguments", items_too_long

# sample
sampled = run("r-5", {"action": "sample", "items": ["a", "b", "c", "d", "e"], "count": 3})
assert sampled.error is None, sampled
sampled_data = json.loads(sampled.content)
assert len(sampled_data["results"]) == 3 and len(set(sampled_data["results"])) == 3, sampled_data

over_sample = run("r-6", {"action": "sample", "items": ["a"], "count": 2, "replacement": False})
assert over_sample.error == "invalid_arguments", over_sample

with_rep = run("r-7", {"action": "sample", "items": ["a"], "count": 3, "replacement": True})
assert with_rep.error is None and json.loads(with_rep.content)["results"] == ["a", "a", "a"], with_rep

# shuffle returns a copy and leaves the input list untouched
original = [1, 2, 3, 4, 5]
orig_copy = list(original)
shuffled = run("r-8", {"action": "shuffle", "items": original, "seed": 99})
assert shuffled.error is None, shuffled
shuffled_data = json.loads(shuffled.content)
assert sorted(shuffled_data["shuffled"]) == orig_copy
assert original == orig_copy, "input list was mutated"

# strict scalar items: booleans and nested values rejected, mixed scalars accepted
bool_items = run("r-9", {"action": "shuffle", "items": [1, True]})
assert bool_items.error == "invalid_arguments", bool_items

nested_items = run("r-10", {"action": "shuffle", "items": [1, [2]]})
assert nested_items.error == "invalid_arguments", nested_items

mixed_scalars = run("r-11", {"action": "shuffle", "items": [1, 2.5, "three"], "seed": 7})
assert mixed_scalars.error is None, mixed_scalars
assert sorted(str(item) for item in json.loads(mixed_scalars.content)["shuffled"]) == ["1", "2.5", "three"], mixed_scalars.content

# action-irrelevant fields are rejected
rep_on_integers = run("r-12", {"action": "integers", "start": 1, "end": 6, "replacement": True})
assert rep_on_integers.error == "invalid_arguments", rep_on_integers

end_on_sample = run("r-13", {"action": "sample", "items": ["a", "b"], "end": 5})
assert end_on_sample.error == "invalid_arguments", end_on_sample

end_on_shuffle = run("r-14", {"action": "shuffle", "items": ["a", "b"], "end": 3})
assert end_on_shuffle.error == "invalid_arguments", end_on_shuffle

count_on_shuffle = run("r-15", {"action": "shuffle", "items": ["a", "b"], "count": 2})
assert count_on_shuffle.error == "invalid_arguments", count_on_shuffle

rep_on_shuffle = run("r-16", {"action": "shuffle", "items": ["a", "b"], "replacement": True})
assert rep_on_shuffle.error == "invalid_arguments", rep_on_shuffle

# seed stays optional for every action
seeded_sample = run("r-17", {"action": "sample", "items": [1, 2, 3], "count": 2, "seed": 5})
assert seeded_sample.error is None and json.loads(seeded_sample.content)["seeded"] is True, seeded_sample
seeded_shuffle = run("r-18", {"action": "shuffle", "items": [1, 2, 3], "seed": 5})
assert seeded_shuffle.error is None and json.loads(seeded_shuffle.content)["seeded"] is True, seeded_shuffle

print("random tool selfcheck OK")
