"""Config flow for BlueSound."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.components import zeroconf
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

KNOWN_HOSTS_SCHEMA = vol.Schema(vol.All(cv.ensure_list, [cv.string]))

_LOGGER = logging.getLogger(__name__)


class FlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Initialize flow."""
        self._host = ""
        self._mac = ""
        self._name = ""

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        return await self.async_step_confirm()

    async def async_step_zeroconf(
        self, discovery_info: zeroconf.ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle a flow initialized by zeroconf discovery."""
        _LOGGER.debug(
            "Discovered new player, %s %s %s %s",
            discovery_info.name,
            discovery_info.ip_address,
            discovery_info.properties.get("deviceid"),
            discovery_info.host,
        )
        if self._async_in_progress() or self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        await self.async_set_unique_id(DOMAIN)

        self._name = discovery_info.name.split(".")[0]
        self._mac = str(discovery_info.properties.get("deviceid"))
        self._host = discovery_info.host

        self.context.update(
            {
                "title_placeholders": {"name": discovery_info.name.split(".")[0]},
                "configuration_url": f"http://{discovery_info.host}",
            }
        )
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input=None) -> ConfigFlowResult:
        """Confirm the setup."""
        errors: dict[str, str] = {}
        _LOGGER.debug(user_input)

        if user_input is not None:
            return self.async_create_entry(title=self._name, data={"host": self._host})
        self._set_confirm_only()

        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"name": self._name, "host": self._host},
            errors=errors,
        )
