"""
Support for Nest thermostats.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/climate.nest/
"""
import logging

import voluptuous as vol

from homeassistant.components.nest import DATA_NEST, SIGNAL_NEST_UPDATE
from homeassistant.components.climate import (
    STATE_AUTO, STATE_COOL, STATE_HEAT, STATE_ECO, ClimateDevice,
    PLATFORM_SCHEMA, ATTR_TARGET_TEMP_HIGH, ATTR_TARGET_TEMP_LOW,
    ATTR_TEMPERATURE, SUPPORT_TARGET_TEMPERATURE,
    SUPPORT_TARGET_TEMPERATURE_HIGH, SUPPORT_TARGET_TEMPERATURE_LOW,
    SUPPORT_OPERATION_MODE, SUPPORT_AWAY_MODE, SUPPORT_FAN_MODE)
from homeassistant.const import (
    TEMP_CELSIUS, TEMP_FAHRENHEIT,
    CONF_SCAN_INTERVAL, STATE_ON, STATE_OFF, STATE_UNKNOWN)
from homeassistant.helpers.dispatcher import async_dispatcher_connect

DEPENDENCIES = ['nest']
_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_SCAN_INTERVAL):
        vol.All(vol.Coerce(int), vol.Range(min=1)),
})

NEST_MODE_HEAT_COOL = 'heat-cool'


def setup_platform(hass, config, add_devices, discovery_info=None):
    """Set up the Nest thermostat.

    No longer in use.
    """


async def async_setup_entry(hass, entry, async_add_devices):
    """Set up the Nest climate device based on a config entry."""
    temp_unit = hass.config.units.temperature_unit

    thermostats = await hass.async_add_job(hass.data[DATA_NEST].thermostats)

    all_devices = [NestThermostat(structure, device, temp_unit)
                   for structure, device in thermostats]

    async_add_devices(all_devices, True)


class NestThermostat(ClimateDevice):
    """Representation of a Nest thermostat."""

    def __init__(self, structure, device, temp_unit):
        """Initialize the thermostat."""
        self._unit = temp_unit
        self.structure = structure
        self._device = device
        self._fan_list = [STATE_ON, STATE_AUTO]

        # Set the default supported features
        self._support_flags = (SUPPORT_TARGET_TEMPERATURE |
                               SUPPORT_OPERATION_MODE | SUPPORT_AWAY_MODE)

        # Not all nest devices support cooling and heating remove unused
        self._operation_list = [STATE_OFF]

        # Add supported nest thermostat features
        if self._device.can_heat:
            self._operation_list.append(STATE_HEAT)

        if self._device.can_cool:
            self._operation_list.append(STATE_COOL)

        if self._device.can_heat and self._device.can_cool:
            self._operation_list.append(STATE_AUTO)
            self._support_flags = (self._support_flags |
                                   SUPPORT_TARGET_TEMPERATURE_HIGH |
                                   SUPPORT_TARGET_TEMPERATURE_LOW)

        self._operation_list.append(STATE_ECO)

        # feature of device
        self._has_fan = self._device.has_fan
        if self._has_fan:
            self._support_flags = (self._support_flags | SUPPORT_FAN_MODE)

        # data attributes
        self._away = None
        self._location = None
        self._name = None
        self._humidity = None
        self._target_temperature = None
        self._temperature = None
        self._temperature_scale = None
        self._mode = None
        self._fan = None
        self._eco_temperature = None
        self._is_locked = None
        self._locked_temperature = None
        self._min_temperature = None
        self._max_temperature = None

    @property
    def should_poll(self):
        """Do not need poll thanks using Nest streaming API."""
        return False

    async def async_added_to_hass(self):
        """Register update signal handler."""
        async def async_update_state():
            """Update device state."""
            await self.async_update_ha_state(True)

        async_dispatcher_connect(self.hass, SIGNAL_NEST_UPDATE,
                                 async_update_state)

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return self._support_flags

    @property
    def unique_id(self):
        """Unique ID for this device."""
        return self._device.serial

    @property
    def name(self):
        """Return the name of the nest, if any."""
        return self._name

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return self._temperature_scale

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._temperature

    @property
    def current_operation(self):
        """Return current operation ie. heat, cool, idle."""
        if self._mode in [STATE_HEAT, STATE_COOL, STATE_OFF, STATE_ECO]:
            return self._mode
        if self._mode == NEST_MODE_HEAT_COOL:
            return STATE_AUTO
        return STATE_UNKNOWN

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        if self._mode != NEST_MODE_HEAT_COOL and \
                self._mode != STATE_ECO and \
                not self.is_away_mode_on:
            return self._target_temperature
        return None

    @property
    def target_temperature_low(self):
        """Return the lower bound temperature we try to reach."""
        if (self.is_away_mode_on or self._mode == STATE_ECO) and \
                self._eco_temperature[0]:
            # eco_temperature is always a low, high tuple
            return self._eco_temperature[0]
        if self._mode == NEST_MODE_HEAT_COOL:
            return self._target_temperature[0]
        return None

    @property
    def target_temperature_high(self):
        """Return the upper bound temperature we try to reach."""
        if (self.is_away_mode_on or self._mode == STATE_ECO) and \
                self._eco_temperature[1]:
            # eco_temperature is always a low, high tuple
            return self._eco_temperature[1]
        if self._mode == NEST_MODE_HEAT_COOL:
            return self._target_temperature[1]
        return None

    @property
    def is_away_mode_on(self):
        """Return if away mode is on."""
        return self._away

    def set_temperature(self, **kwargs):
        """Set new target temperature."""
        import nest
        temp = None
        target_temp_low = kwargs.get(ATTR_TARGET_TEMP_LOW)
        target_temp_high = kwargs.get(ATTR_TARGET_TEMP_HIGH)
        if self._mode == NEST_MODE_HEAT_COOL:
            if target_temp_low is not None and target_temp_high is not None:
                temp = (target_temp_low, target_temp_high)
                _LOGGER.debug("Nest set_temperature-output-value=%s", temp)
        else:
            temp = kwargs.get(ATTR_TEMPERATURE)
            _LOGGER.debug("Nest set_temperature-output-value=%s", temp)
        try:
            if temp is not None:
                self._device.target = temp
        except nest.nest.APIError as api_error:
            _LOGGER.error("An error occurred while setting temperature: %s",
                          api_error)
            # restore target temperature
            self.schedule_update_ha_state(True)

    def set_operation_mode(self, operation_mode):
        """Set operation mode."""
        if operation_mode in [STATE_HEAT, STATE_COOL, STATE_OFF, STATE_ECO]:
            device_mode = operation_mode
        elif operation_mode == STATE_AUTO:
            device_mode = NEST_MODE_HEAT_COOL
        else:
            device_mode = STATE_OFF
            _LOGGER.error(
                "An error occurred while setting device mode. "
                "Invalid operation mode: %s", operation_mode)
        self._device.mode = device_mode

    @property
    def operation_list(self):
        """List of available operation modes."""
        return self._operation_list

    def turn_away_mode_on(self):
        """Turn away on."""
        self.structure.away = True

    def turn_away_mode_off(self):
        """Turn away off."""
        self.structure.away = False

    @property
    def current_fan_mode(self):
        """Return whether the fan is on."""
        if self._has_fan:
            # Return whether the fan is on
            return STATE_ON if self._fan else STATE_AUTO
        # No Fan available so disable slider
        return None

    @property
    def fan_list(self):
        """List of available fan modes."""
        if self._has_fan:
            return self._fan_list
        return None

    def set_fan_mode(self, fan_mode):
        """Turn fan on/off."""
        if self._has_fan:
            self._device.fan = fan_mode.lower()

    @property
    def min_temp(self):
        """Identify min_temp in Nest API or defaults if not available."""
        return self._min_temperature

    @property
    def max_temp(self):
        """Identify max_temp in Nest API or defaults if not available."""
        return self._max_temperature

    def update(self):
        """Cache value from Python-nest."""
        self._location = self._device.where
        self._name = self._device.name
        self._humidity = self._device.humidity
        self._temperature = self._device.temperature
        self._mode = self._device.mode
        self._target_temperature = self._device.target
        self._fan = self._device.fan
        self._away = self.structure.away == 'away'
        self._eco_temperature = self._device.eco_temperature
        self._locked_temperature = self._device.locked_temperature
        self._min_temperature = self._device.min_temperature
        self._max_temperature = self._device.max_temperature
        self._is_locked = self._device.is_locked
        if self._device.temperature_scale == 'C':
            self._temperature_scale = TEMP_CELSIUS
        else:
            self._temperature_scale = TEMP_FAHRENHEIT
