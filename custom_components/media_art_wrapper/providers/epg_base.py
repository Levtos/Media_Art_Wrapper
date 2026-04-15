"""EPG provider helpers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from homeassistant.core import HomeAssistant


@dataclass(slots=True)
class EPGProgram:
    title: str
    sub_title: str
    description: str
    channel_name: str
    channel_icon: str | None = None


class HaEpgProvider:
    """Reads current program from HA-EPG sensor attributes."""

    async def get_current_program(self, hass: HomeAssistant, sensor_entity_id: str) -> EPGProgram | None:
        state = hass.states.get(sensor_entity_id)
        if not state:
            return None

        today = state.attributes.get("today", {})
        if not isinstance(today, dict):
            return None
        now = datetime.now().strftime("%H:%M")

        current = None
        for slot_time, program in sorted(today.items()):
            if not isinstance(program, dict):
                continue
            slot_start = str(program.get("start", slot_time))
            slot_end = str(program.get("end", "23:59"))
            if slot_start <= now < slot_end:
                current = program
                break

        if not current:
            return None

        return EPGProgram(
            title=str(current.get("title", "")),
            sub_title=str(current.get("sub_title", "")),
            description=str(current.get("desc", "")),
            channel_name=str(state.attributes.get("channel_display_name", "")),
            channel_icon=state.attributes.get("channel_icon"),
        )
