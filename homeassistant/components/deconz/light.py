"""Support for deCONZ lights."""
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP,
    ATTR_EFFECT,
    ATTR_FLASH,
    ATTR_HS_COLOR,
    ATTR_TRANSITION,
    DOMAIN,
    EFFECT_COLORLOOP,
    FLASH_LONG,
    FLASH_SHORT,
    SUPPORT_BRIGHTNESS,
    SUPPORT_COLOR,
    SUPPORT_COLOR_TEMP,
    SUPPORT_EFFECT,
    SUPPORT_FLASH,
    SUPPORT_TRANSITION,
    LightEntity,
)
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
import homeassistant.util.color as color_util

from .const import (
    CONF_GROUP_ID_BASE,
    COVER_TYPES,
    DOMAIN as DECONZ_DOMAIN,
    LOCK_TYPES,
    NEW_GROUP,
    NEW_LIGHT,
    SWITCH_TYPES,
)
from .deconz_device import DeconzDevice
from .gateway import get_gateway_from_config_entry


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the deCONZ lights and groups from a config entry."""
    gateway = get_gateway_from_config_entry(hass, config_entry)
    gateway.entities[DOMAIN] = set()

    @callback
    def async_add_light(lights):
        """Add light from deCONZ."""
        entities = []

        for light in lights:
            if (
                light.type not in COVER_TYPES + LOCK_TYPES + SWITCH_TYPES
                and light.uniqueid not in gateway.entities[DOMAIN]
            ):
                entities.append(DeconzLight(light, gateway))

        if entities:
            async_add_entities(entities, True)

    gateway.listeners.append(
        async_dispatcher_connect(
            hass, gateway.async_signal_new_device(NEW_LIGHT), async_add_light
        )
    )

    @callback
    def async_add_group(groups):
        """Add group from deCONZ."""
        if not gateway.option_allow_deconz_groups:
            return

        entities = []

        for group in groups:
            if not group.lights:
                continue

            known_groups = set(gateway.entities[DOMAIN])
            new_group = DeconzGroup(group, gateway)
            if new_group.unique_id not in known_groups:
                entities.append(new_group)

        if entities:
            async_add_entities(entities, True)

    gateway.listeners.append(
        async_dispatcher_connect(
            hass, gateway.async_signal_new_device(NEW_GROUP), async_add_group
        )
    )

    async_add_light(gateway.api.lights.values())
    async_add_group(gateway.api.groups.values())


class DeconzBaseLight(DeconzDevice, LightEntity):
    """Representation of a deCONZ light."""

    TYPE = DOMAIN

    def __init__(self, device, gateway):
        """Set up light."""
        super().__init__(device, gateway)

        self._features = 0

        if self._device.brightness is not None:
            self._features |= SUPPORT_BRIGHTNESS
            self._features |= SUPPORT_FLASH
            self._features |= SUPPORT_TRANSITION

        if self._device.ct is not None:
            self._features |= SUPPORT_COLOR_TEMP

        if self._device.xy is not None:
            self._features |= SUPPORT_COLOR

        if self._device.effect is not None:
            self._features |= SUPPORT_EFFECT

    @property
    def brightness(self):
        """Return the brightness of this light between 0..255."""
        return self._device.brightness

    @property
    def effect_list(self):
        """Return the list of supported effects."""
        return [EFFECT_COLORLOOP]

    @property
    def color_temp(self):
        """Return the CT color value."""
        if self._device.colormode != "ct":
            return None

        return self._device.ct

    @property
    def hs_color(self):
        """Return the hs color value."""
        if self._device.colormode in ("xy", "hs") and self._device.xy:
            return color_util.color_xy_to_hs(*self._device.xy)
        return None

    @property
    def is_on(self):
        """Return true if light is on."""
        return self._device.state

    @property
    def supported_features(self):
        """Flag supported features."""
        return self._features

    async def async_turn_on(self, **kwargs):
        """Turn on light."""
        data = {"on": True}

        if ATTR_COLOR_TEMP in kwargs:
            data["ct"] = kwargs[ATTR_COLOR_TEMP]

        if ATTR_HS_COLOR in kwargs:
            data["xy"] = color_util.color_hs_to_xy(*kwargs[ATTR_HS_COLOR])

        if ATTR_BRIGHTNESS in kwargs:
            data["bri"] = kwargs[ATTR_BRIGHTNESS]

        if ATTR_TRANSITION in kwargs:
            data["transitiontime"] = int(kwargs[ATTR_TRANSITION] * 10)
        elif "IKEA" in self._device.manufacturer:
            data["transitiontime"] = 0

        if ATTR_FLASH in kwargs:
            if kwargs[ATTR_FLASH] == FLASH_SHORT:
                data["alert"] = "select"
                del data["on"]
            elif kwargs[ATTR_FLASH] == FLASH_LONG:
                data["alert"] = "lselect"
                del data["on"]

        if ATTR_EFFECT in kwargs:
            if kwargs[ATTR_EFFECT] == EFFECT_COLORLOOP:
                data["effect"] = "colorloop"
            else:
                data["effect"] = "none"

        await self._device.async_set_state(data)

    async def async_turn_off(self, **kwargs):
        """Turn off light."""
        if not self._device.state:
            return

        data = {"on": False}

        if ATTR_TRANSITION in kwargs:
            data["bri"] = 0
            data["transitiontime"] = int(kwargs[ATTR_TRANSITION] * 10)

        if ATTR_FLASH in kwargs:
            if kwargs[ATTR_FLASH] == FLASH_SHORT:
                data["alert"] = "select"
                del data["on"]
            elif kwargs[ATTR_FLASH] == FLASH_LONG:
                data["alert"] = "lselect"
                del data["on"]

        await self._device.async_set_state(data)

    @property
    def device_state_attributes(self):
        """Return the device state attributes."""
        return {"is_deconz_group": self._device.type == "LightGroup"}


class DeconzLight(DeconzBaseLight):
    """Representation of a deCONZ light."""

    @property
    def max_mireds(self):
        """Return the warmest color_temp that this light supports."""
        return self._device.ctmax or super().max_mireds

    @property
    def min_mireds(self):
        """Return the coldest color_temp that this light supports."""
        return self._device.ctmin or super().min_mireds


class DeconzGroup(DeconzBaseLight):
    """Representation of a deCONZ group."""

    def __init__(self, device, gateway):
        """Set up group and create an unique id."""
        group_id_base = gateway.config_entry.unique_id
        if CONF_GROUP_ID_BASE in gateway.config_entry.data:
            group_id_base = gateway.config_entry.data[CONF_GROUP_ID_BASE]
        self._unique_id = f"{group_id_base}-{device.deconz_id}"

        super().__init__(device, gateway)

    @property
    def unique_id(self):
        """Return a unique identifier for this device."""
        return self._unique_id

    @property
    def device_info(self):
        """Return a device description for device registry."""
        bridgeid = self.gateway.api.config.bridgeid

        return {
            "identifiers": {(DECONZ_DOMAIN, self.unique_id)},
            "manufacturer": "Dresden Elektronik",
            "model": "deCONZ group",
            "name": self._device.name,
            "via_device": (DECONZ_DOMAIN, bridgeid),
        }

    @property
    def device_state_attributes(self):
        """Return the device state attributes."""
        attributes = dict(super().device_state_attributes)
        attributes["all_on"] = self._device.all_on

        return attributes
