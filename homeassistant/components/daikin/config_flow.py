"""Config flow for the Daikin platform."""
import asyncio
import logging
import uuid

from aiohttp import ClientError
from async_timeout import timeout
from pydaikin.appliance import Appliance
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST

from .const import CONF_KEY, CONF_UUID, KEY_IP, KEY_MAC

_LOGGER = logging.getLogger(__name__)


@config_entries.HANDLERS.register("daikin")
class FlowHandler(config_entries.ConfigFlow):
    """Handle a config flow."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    async def _create_entry(self, host, mac, key=None, uuid=None):
        """Register new entry."""
        # Check if mac already is registered
        for entry in self._async_current_entries():
            if entry.data[KEY_MAC] == mac:
                return self.async_abort(reason="already_configured")

        return self.async_create_entry(
            title=host,
            data={CONF_HOST: host, KEY_MAC: mac, CONF_KEY: key, CONF_UUID: uuid},
        )

    async def _create_device(self, host, key=None):
        """Create device."""

        # BRP07Cxx devices needs uuid together with key
        if key is not None and not "":
            _uuid = str(uuid.uuid1())
        else:
            _uuid = None
            key = None

        try:
            device = Appliance(
                host,
                self.hass.helpers.aiohttp_client.async_get_clientsession(),
                key,
                _uuid,
            )
            with timeout(60):
                await device.init()
        except asyncio.TimeoutError:
            return self.async_abort(reason="device_timeout")
        except ClientError:
            _LOGGER.exception("ClientError")
            return self.async_abort(reason="device_fail")
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected error creating device")
            return self.async_abort(reason="device_fail")

        mac = device.values.get("mac")
        return await self._create_entry(host, mac, key, _uuid)

    async def async_step_user(self, user_input=None):
        """User initiated config flow."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {vol.Required(CONF_HOST): str, vol.Optional(CONF_KEY): str}
                ),
            )
        return await self._create_device(
            user_input[CONF_HOST], user_input.get(CONF_KEY)
        )

    async def async_step_import(self, user_input):
        """Import a config entry."""
        host = user_input.get(CONF_HOST)
        key = user_input.get(CONF_KEY)
        if not host:
            return await self.async_step_user()
        return await self._create_device(host, key)

    async def async_step_discovery(self, user_input):
        """Initialize step from discovery."""
        _LOGGER.info("Discovered device: %s", user_input)
        return await self._create_entry(user_input[KEY_IP], user_input[KEY_MAC])
