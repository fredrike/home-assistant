"""YoLink device number type config settings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from yolink.client_request import ClientRequest
from yolink.const import ATTR_DEVICE_SPEAKER_HUB
from yolink.device import YoLinkDevice

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import YoLinkCoordinator
from .entity import YoLinkEntity

OPTIONS_VALUME = "options_volume"


@dataclass(frozen=True, kw_only=True)
class YoLinkNumberTypeConfigEntityDescription(NumberEntityDescription):
    """YoLink NumberEntity description."""

    exists_fn: Callable[[YoLinkDevice], bool]
    value: Callable


NUMBER_TYPE_CONF_SUPPORT_DEVICES = [ATTR_DEVICE_SPEAKER_HUB]

SUPPORT_SET_VOLUME_DEVICES = [ATTR_DEVICE_SPEAKER_HUB]

DEVICE_CONFIG_DESCRIPTIONS: tuple[YoLinkNumberTypeConfigEntityDescription, ...] = (
    YoLinkNumberTypeConfigEntityDescription(
        key=OPTIONS_VALUME,
        translation_key="config_volume",
        native_min_value=1,
        native_max_value=16,
        mode=NumberMode.SLIDER,
        native_step=1.0,
        native_unit_of_measurement=None,
        icon="mdi:volume-high",
        exists_fn=lambda device: device.device_type in SUPPORT_SET_VOLUME_DEVICES,
        value=lambda state: state["options"]["volume"],
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up device number type config option entity from a config entry."""
    device_coordinators = hass.data[DOMAIN][config_entry.entry_id].device_coordinators
    config_device_coordinators = [
        device_coordinator
        for device_coordinator in device_coordinators.values()
        if device_coordinator.device.device_type in NUMBER_TYPE_CONF_SUPPORT_DEVICES
    ]
    entities = []
    for config_device_coordinator in config_device_coordinators:
        for description in DEVICE_CONFIG_DESCRIPTIONS:
            if description.exists_fn(config_device_coordinator.device):
                entities.append(
                    YoLinkNumberTypeConfigEntity(
                        config_entry,
                        config_device_coordinator,
                        description,
                    )
                )
    async_add_entities(entities)


class YoLinkNumberTypeConfigEntity(YoLinkEntity, NumberEntity):
    """YoLink number type config Entity."""

    entity_description: YoLinkNumberTypeConfigEntityDescription

    def __init__(
        self,
        config_entry: ConfigEntry,
        coordinator: YoLinkCoordinator,
        description: YoLinkNumberTypeConfigEntityDescription,
    ) -> None:
        """Init YoLink device number type config entities."""
        super().__init__(config_entry, coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.device.device_id} {description.key}"

    @callback
    def update_entity_state(self, state: dict) -> None:
        """Update HA Entity State."""
        attr_val = self.entity_description.value(state)
        self._attr_native_value = attr_val
        self.async_write_ha_state()

    async def update_speaker_hub_volume(self, volume: float) -> None:
        """Update SpeakerHub volume."""
        await self.call_device(ClientRequest("setOption", {"volume": volume}))

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        if (
            self.coordinator.device.device_type == ATTR_DEVICE_SPEAKER_HUB
            and self.entity_description.key == OPTIONS_VALUME
        ):
            await self.update_speaker_hub_volume(value)
            self._attr_native_value = value
            self.async_write_ha_state()
