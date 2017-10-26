"""
Support for Telldus Live.

For more details about this component, please refer to the documentation at
https://home-assistant.io/components/tellduslive/
"""
import json
from datetime import datetime, timedelta
import os
import asyncio
import logging

from homeassistant.const import (
    ATTR_BATTERY_LEVEL, DEVICE_DEFAULT_NAME)
from homeassistant.helpers import discovery
from homeassistant.components.discovery import SERVICE_TELLDUSLIVE
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import track_point_in_utc_time
from homeassistant.util.dt import utcnow
import voluptuous as vol

DOMAIN = 'tellduslive'

REQUIREMENTS = ['tellduslive==0.4.0']

_LOGGER = logging.getLogger(__name__)

TELLLDUS_CONFIG_FILE = 'tellduslive.conf'
KEY_CONFIG = 'tellduslive_config'

CONF_PUBLIC_KEY = 'public_key'
CONF_PRIVATE_KEY = 'private_key'
CONF_TOKEN = 'token'
CONF_TOKEN_SECRET = 'token_secret'
CONF_HOST = 'host'
CONF_UPDATE_INTERVAL = 'update_interval'

LOCAL_API_DEVICES = ['TellstickZnet', 'TellstickNetV2']

MIN_UPDATE_INTERVAL = timedelta(seconds=5)
DEFAULT_UPDATE_INTERVAL = timedelta(minutes=1)

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Optional(CONF_PUBLIC_KEY): cv.string,
        vol.Optional(CONF_PRIVATE_KEY): cv.string,
        vol.Optional(CONF_TOKEN): cv.string,
        vol.Optional(CONF_TOKEN_SECRET): cv.string,
        vol.Optional(CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL): (
            vol.All(cv.time_period, vol.Clamp(min=MIN_UPDATE_INTERVAL)))
    }),
}, extra=vol.ALLOW_EXTRA)


ATTR_LAST_UPDATED = 'time_last_updated'


def setup(hass, config, local=None, oauth=None):
    """Set up the Telldus Live component."""

    config_filename = hass.config.path(TELLLDUS_CONFIG_FILE)

    def save_config(config=None):
        """Save configuration."""
        try:
            with open(config_filename, 'w') as f:
                f.write(json.dumps(config))
            return True
        except IOError as error:
            _LOGGER.error("Saving config file failed: %s", error)
 
    def load_config():
        """Load configuration:"""
        if not os.path.isfile(config_filename):
            return {}
        try:
            with open(config_filename) as f:
                return json.loads(f.read())
        except (ValueError, IOError) as error:
            _LOGGER.error("Reading config file failed: %s", error)

    def request_configuration(host=None):
        """Request TelldusLive authorized."""

        configurator = hass.components.configurator
        hass.data.setdefault(KEY_CONFIG, {})
        instance = hass.data[KEY_CONFIG].get(host)

        # Configuration already in progress
        if instance:
            return

        _LOGGER.info('Configuring TelldusLive {}'.format(
            'local client: {}'.format(host) if host else
            'cloud service'))

        from tellduslive import Client
        auth_url, request_token = Client.get_authorize_url(host, app='HA')
        if not auth_url:
            return

        def configuration_callback(callback_data):
            """Handle the submitted configuration."""
            from tellduslive import Client
            access_token = Client.authorize_local_api(host, request_token)
            res = setup(hass, config, local={CONF_HOST: host, CONF_TOKEN: access_token})
            if not res:
                hass.async_add_job(configurator.notify_errors, instance,
                                   "Unable to connect.")
                return

            @asyncio.coroutine
            def success():
                """Set up was successful."""
                # Save config
                if not load_config(
                        {host: {
                            CONF_TOKEN: access_token,
                        }}):
                    _LOGGER.error("Failed to save configuration file")
                hass.async_add_job(configurator.request_done, instance)

            hass.async_add_job(success)

        hass.data[KEY_CONFIG][host] = configurator.request_config(
            'TelldusLive ({})'.format('LocalAPI' if host else 'Cloud service'),
            configuration_callback,
            description=('To link your TelldusLive account ',
                        'click the link, login, and authorize:'),
            submit_caption='I authorized successfully',
            link_name="Link TelldusLive account",
            link_url=auth_url,
            entity_picture='/static/images/logo_tellduslive.png',
        )

    def tellstick_discovered(service, info):
        """Run when a Tellstick is discovered."""
        if DOMAIN in hass.data:
            return  # Tellstick already configured
        host, device = info
        if not any(x in device for x in LOCAL_API_DEVICES):
            hass.async_add_job(request_configuration)
            return

        file_config = load_config()
        if file_config:
            file_host, _ = file_config.popitem()
            if file_host == host:
                return
        hass.async_add_job(request_configuration)
        hass.async_add_job(request_configuration, host)

    discovery.async_listen(hass, SERVICE_TELLDUSLIVE, tellstick_discovered)

    host = None
    token = None
    # get config from tellduslive.conf
    file_config = load_config()
    # Via discovery
    if local is not None:
        # Parse discovery data
        host = local[CONF_HOST]
        token = local[CONF_TOKEN]
        _LOGGER.info("Discovered TelldusLive controller: %s", host)
    elif file_config and oauth is None:  # Test oauth so we don't overwrite user settings from file.
        # Setup a configured TellStick
        host, host_config = file_config.popitem()
        if host == DOMAIN:  # We have a tellduslive.conf entry
            host = None
            oauth = host_config
        else:
            token = host_config[CONF_TOKEN]

    cnf = config.get(DOMAIN, {})
    cnf_live = all((cnf.get(CONF_PUBLIC_KEY) is None,
                    cnf.get(CONF_PRIVATE_KEY) is None,
                    cnf.get(CONF_TOKEN) is None,
                    cnf.get(CONF_TOKEN_SECRET) is None))
    if host is None and oauth is None and cnf_live:
        if cnf_live:
            _LOGGER.info("Configure TelldusLive")
            hass.async_add_job(request_configuration)
        return True

    client = TelldusLiveClient(hass, config, host, token, oauth)

    if not client.validate_session():
        _LOGGER.error(
            "Authentication Error: Please make sure you have configured your "
            "keys that can be acquired from "
            "https://api.telldus.com/keys/index")

        return False

    hass.data[DOMAIN] = client

    client.update()

    return True


class TelldusLiveClient(object):
    """Get the latest data and update the states."""

    def __init__(self, hass, config, host=None, token=None, oauth=None):
        """Initialize the Tellus data object."""
        from tellduslive import Client

        self.entities = []

        self._hass = hass
        self._config = config
        self._host = host

        if host is not None:
            public_key = None
            private_key = None
            token_secret = None
        elif oauth is not None:
            public_key = oauth[CONF_PUBLIC_KEY]
            private_key = oauth[CONF_PRIVATE_KEY]
            token = oauth[CONF_TOKEN]
            token_secret = oauth[CONF_TOKEN_SECRET]
        else:
            public_key = config[DOMAIN].get(CONF_PUBLIC_KEY)
            private_key = config[DOMAIN].get(CONF_PRIVATE_KEY)
            token = config[DOMAIN].get(CONF_TOKEN)
            token_secret = config[DOMAIN].get(CONF_TOKEN_SECRET)

        self._interval = config.get(DOMAIN, {}).get(CONF_UPDATE_INTERVAL)
        if self._interval is None:
            self._interval = DEFAULT_UPDATE_INTERVAL
        _LOGGER.debug('Update interval %s', self._interval)

        self._client = Client(public_key,
                              private_key,
                              token,
                              token_secret,
                              host)

    def validate_session(self):
        """Make a request to see if the session is valid."""
        if self._host is not None:
            return self._client.refresh_local_token()  # TODO, add timer so the token will be renewed before it expires.
        response = self._client.request_user()
        return response and 'email' in response

    def update(self, *args):
        """Periodically poll the servers for current state."""
        _LOGGER.debug("Updating")
        try:
            self._sync()
        finally:
            track_point_in_utc_time(
                self._hass, self.update, utcnow() + self._interval)

    def _sync(self):
        """Update local list of devices."""
        if not self._client.update():
            _LOGGER.warning("Failed request")

        def identify_device(device):
            """Find out what type of HA component to create."""
            from tellduslive import (DIM, UP, TURNON)
            if device.methods & DIM:
                return 'light'
            elif device.methods & UP:
                return 'cover'
            elif device.methods & TURNON:
                return 'switch'
            _LOGGER.warning(
                "Unidentified device type (methods: %d)", device.methods)
            return 'switch'

        def discover(device_id, component):
            """Discover the component."""
            discovery.load_platform(
                self._hass, component, DOMAIN, [device_id], self._config)

        known_ids = {entity.device_id for entity in self.entities}
        for device in self._client.devices:
            if device.device_id in known_ids:
                continue
            if device.is_sensor:
                for item in device.items:
                    discover((device.device_id, item.name, item.scale),
                             'sensor')
            else:
                discover(device.device_id,
                         identify_device(device))

        for entity in self.entities:
            entity.changed()

    def device(self, device_id):
        """Return device representation."""
        return self._client.device(device_id)

    def is_available(self, device_id):
        """Return device availability."""
        return device_id in self._client.device_ids


class TelldusLiveEntity(Entity):
    """Base class for all Telldus Live entities."""

    def __init__(self, hass, device_id):
        """Initialize the entity."""
        self._id = device_id
        self._client = hass.data[DOMAIN]
        self._client.entities.append(self)
        self._name = self.device.name
        _LOGGER.debug("Created device %s", self)

    def changed(self):
        """Return the property of the device might have changed."""
        if self.device.name:
            self._name = self.device.name
        self.schedule_update_ha_state()

    @property
    def device_id(self):
        """Return the id of the device."""
        return self._id

    @property
    def device(self):
        """Return the representation of the device."""
        return self._client.device(self.device_id)

    @property
    def _state(self):
        """Return the state of the device."""
        return self.device.state

    @property
    def should_poll(self):
        """Return the polling state."""
        return False

    @property
    def assumed_state(self):
        """Return true if unable to access real state of entity."""
        return True

    @property
    def name(self):
        """Return name of device."""
        return self._name or DEVICE_DEFAULT_NAME

    @property
    def available(self):
        """Return true if device is not offline."""
        return self._client.is_available(self.device_id)

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        attrs = {}
        if self._battery_level:
            attrs[ATTR_BATTERY_LEVEL] = self._battery_level
        if self._last_updated:
            attrs[ATTR_LAST_UPDATED] = self._last_updated
        return attrs

    @property
    def _battery_level(self):
        """Return the battery level of a device."""
        return round(self.device.battery * 100 / 255) \
            if self.device.battery else None

    @property
    def _last_updated(self):
        """Return the last update of a device."""
        return str(datetime.fromtimestamp(self.device.lastUpdated)) \
            if self.device.lastUpdated else None
