"""Climate platform that offers a climate device for the TFIAC protocol."""
from concurrent.futures import _base as futures
import logging
from time import timedelta

import voluptuous as vol

from homeassistant.components.climate import PLATFORM_SCHEMA, ClimateDevice
from homeassistant.components.climate.const import (
    STATE_AUTO, STATE_COOL, STATE_DRY, STATE_FAN_ONLY, STATE_HEAT,
    SUPPORT_FAN_MODE, SUPPORT_ON_OFF, SUPPORT_OPERATION_MODE,
    SUPPORT_SWING_MODE, SUPPORT_TARGET_TEMPERATURE)
from homeassistant.const import (
    ATTR_TEMPERATURE, CONF_HOST, EVENT_HOMEASSISTANT_STOP, TEMP_FAHRENHEIT)
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv
from homeassistant.util import Throttle
from homeassistant.util.temperature import convert as convert_temperature

DOMAIN = 'tfiac'

MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=60)

REQUIREMENTS = ['pytfiac==0.2']

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_HOST): cv.string,
})

_LOGGER = logging.getLogger(__name__)

MIN_TEMP = 61
MAX_TEMP = 88
OPERATION_LIST = {
    STATE_HEAT: 'heat',
    STATE_AUTO: 'selfFeel',
    STATE_DRY: 'dehumi',
    STATE_FAN_ONLY: 'fan',
    STATE_COOL: 'cool',
}
FAN_LIST = ['Auto', 'Low', 'Middle', 'High']
SWING_LIST = [
    'Off',
    'Vertical',
    'Horizontal',
    'Both',
]

CURR_TEMP = 'current_temp'
TARGET_TEMP = 'target_temp'
OPERATION_MODE = 'operation'
FAN_MODE = 'fan_mode'
SWING_MODE = 'swing_mode'
ON_MODE = 'is_on'


async def async_setup_platform(hass, config, async_add_devices,
                               discovery_info=None):
    """Set up the TFIAC climate device."""
    from pytfiac import Tfiac

    host = config.get(CONF_HOST)
    if host is not None:
        tfiac_client = Tfiac(host)
        await tfiac_client.update()
        async_add_devices([TfiacClimate(hass, tfiac_client)])


class TfiacClimate(ClimateDevice):
    """TFIAC class."""

    def __init__(self, hass, client):
        """Init class."""
        hass.data[DOMAIN] = self
        self._client = client
        self._available = True

        connect_task = hass.loop.create_task(
            client.start(self.schedule_update_ha_state))

        @callback
        def gw_stop(event):
            """Trigger to stop the gateway."""
            client.stop()
            if not connect_task.done():
                connect_task.cancel()
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, gw_stop)

    @property
    def should_poll(self):
        """Return False as this is local push."""
        return False

    @property
    def available(self):
        """Return if the device is available."""
        return self._available

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    async def async_update(self):
        """Update status via socket polling."""
        try:
            await self._client.update()
            self._available = True
        except futures.TimeoutError:
            self._available = False

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return (SUPPORT_FAN_MODE | SUPPORT_ON_OFF | SUPPORT_OPERATION_MODE
                | SUPPORT_SWING_MODE | SUPPORT_TARGET_TEMPERATURE)

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        return convert_temperature(MIN_TEMP, TEMP_FAHRENHEIT,
                                   self.temperature_unit)

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        return convert_temperature(MAX_TEMP, TEMP_FAHRENHEIT,
                                   self.temperature_unit)

    @property
    def name(self):
        """Return the name of the climate device."""
        return self._client.name

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._client.status['target_temp']

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return TEMP_FAHRENHEIT

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._client.status['current_temp']

    @property
    def current_operation(self):
        """Return current operation ie. heat, cool, idle."""
        operation = self._client.status['operation']
        return {v: k
                for k, v in OPERATION_LIST.items()}.get(operation, operation)

    @property
    def is_on(self):
        """Return true if on."""
        return self._client.status[ON_MODE] == 'on'

    @property
    def operation_list(self):
        """Return the list of available operation modes."""
        return sorted(OPERATION_LIST)

    @property
    def current_fan_mode(self):
        """Return the fan setting."""
        return self._client.status['fan_mode']

    @property
    def fan_list(self):
        """Return the list of available fan modes."""
        return FAN_LIST

    @property
    def current_swing_mode(self):
        """Return the swing setting."""
        return self._client.status['swing_mode']

    @property
    def swing_list(self):
        """List of available swing modes."""
        return SWING_LIST

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        if kwargs.get(ATTR_TEMPERATURE) is not None:
            await self._client.set_state(TARGET_TEMP,
                                         kwargs.get(ATTR_TEMPERATURE))

    async def async_set_operation_mode(self, operation_mode):
        """Set new operation mode."""
        await self._client.set_state(OPERATION_MODE,
                                     OPERATION_LIST[operation_mode])

    async def async_set_fan_mode(self, fan_mode):
        """Set new fan mode."""
        await self._client.set_state(FAN_MODE, fan_mode)

    async def async_set_swing_mode(self, swing_mode):
        """Set new swing mode."""
        await self._client.set_swing(swing_mode)

    async def async_turn_on(self):
        """Turn device on."""
        await self._client.set_state(ON_MODE, 'on')

    async def async_turn_off(self):
        """Turn device off."""
        await self._client.set_state(ON_MODE, 'off')
