import pytest
from pydantic import ValidationError

from week23_production_lab.domain import EchoCommand, SumCommand, execute


def test_sum_is_deterministic_and_bounded() -> None:
    command = SumCommand(operation="sum", input={"numbers": [4, -2, 11]})

    assert execute(command) == {"total": 13}


def test_echo_is_deterministic() -> None:
    command = EchoCommand(operation="echo", input={"message": "hello lab"})

    assert execute(command) == {"message": "hello lab"}


@pytest.mark.parametrize("numbers", [[], list(range(17))])
def test_sum_rejects_empty_or_oversized_work(numbers: list[int]) -> None:
    with pytest.raises(ValidationError):
        SumCommand(operation="sum", input={"numbers": numbers})


def test_commands_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        EchoCommand(operation="echo", input={"message": "ok", "secret": "no"})
