import logging
from math import pow

from pitop.common.common_ids import DeviceID
from smbus2 import SMBus

from ..sys_config import HDMI, I2S, UART

logger = logging.getLogger(__name__)

_bus_id = 1
_device_addr = 0x24
_host_device_id = DeviceID.unknown

_speaker_bit = 0
_mcu_bit = 1
_eeprom_bit = 2
_16khz_bit = 3

#######################
# INTERNAL OPERATIONS #
#######################


def _get_addr_for_bit(bit):
    if bit in [0, 1, 2, 3]:
        logger.debug("bit:  " + str(bit))
        addr = int(pow(2, bit))
        logger.debug("addr: " + str(addr))
        return addr
    else:
        logger.warning("Internal ERROR: invalid bit; cannot get address")
        return -1


def _get_bit_string(value):
    """INTERNAL.

    Get string representation of an int in binary
    """

    return "{0:b}".format(value).zfill(8)


def _update_device_state_bit(bit, value):
    """INTERNAL.

    Set a particular device state bit to enable or disable a particular
    function
    """

    # Bits:  0x0000
    # Index:   3210

    if bit not in [0, 1, 2, 3]:
        logger.warning("Error: Not a valid state bit")
        return False

    try:
        current_state = _read_device_state()
        logger.debug("Current device state: " + _get_bit_string(current_state))

    except Exception:
        logger.warning("Error: There was a problem getting the current device state")
        return False

    # Get the bit mask for the new state
    new_state = _get_addr_for_bit(bit)

    if value == 0:
        new_state = ~new_state

    # Check if there is anything to do
    if (value == 1 and (new_state & current_state) != 0) or (
        value == 0 and (~new_state & ~current_state) != 0
    ):
        logger.debug("Warning: Mode already set, nothing to send")
        return True

    if value == 0:
        new_state = new_state & current_state
    else:
        new_state = new_state | current_state

    # Combine the old with the new and send
    return _write_device_state(new_state)


def _verify_device_state(expected_state):
    """INTERNAL.

    Verify that that current device state matches that expected
    """

    current_state = _read_device_state()

    if expected_state == current_state:
        return True

    else:
        logger.warning(
            "Error: Device write verification failed. Expected: "
            + _get_bit_string(expected_state)
            + " Received: "
            + _get_bit_string(current_state)
        )
        return False


def _write_device_state(state):
    """INTERNAL.

    Send the state bits across the I2C bus
    """

    try:
        logger.debug("Connecting to bus...")
        i2c_bus = SMBus(_bus_id)

        state_to_send = 0x0F & state

        logger.debug("Writing new state:    " + _get_bit_string(state_to_send))
        i2c_bus.write_byte_data(_device_addr, 0, state_to_send)

        result = _verify_device_state(state_to_send)

        if result is True:
            logger.debug("OK")
        else:
            logger.warning("Error: New state could not be verified")

        return result

    except Exception:
        logger.warning("Error: There was a problem writing to the device")
        return False


def _read_device_state():
    """INTERNAL.

    Read from the I2C bus to get the current state of the pulse. Caller
    should handle exceptions
    """

    try:
        logger.debug("Connecting to bus...")
        i2c_bus = SMBus(_bus_id)

        current_state = i2c_bus.read_byte(_device_addr) & 0x0F

        return int(current_state)

    except Exception:
        logger.warning("Error: There was a problem reading from the device")
        # Best to re-raise as we can't recover from this
        raise


def _reset_device_state(enable):
    """Reset the device state bits to the default enabled or disabled state."""

    clean_enable_state = _get_addr_for_bit(_eeprom_bit)
    clean_disable_state = _get_addr_for_bit(_speaker_bit) | _get_addr_for_bit(_mcu_bit)

    state_to_send = clean_enable_state if enable else clean_disable_state
    return _write_device_state(state_to_send)


def _check_and_set_I2S_config(i2s_required):
    reboot_required = False

    if I2S.get_current_state() is not i2s_required:
        I2S.set_state(i2s_required)
        reboot_required = True
    else:
        reboot_required = False

    return reboot_required


def _check_and_set_serial_config():
    reboot_required = False

    if UART.enabled() is True:
        logger.debug("UART is already enabled")
    else:
        logger.debug("UART NOT already enabled, enabling...")
        UART.set_enable(True)  # UART.configure_in_boot_config(enable_uart=1)
        reboot_required = True

    reboot_required = UART.remove_serial_from_cmdline() or reboot_required
    return reboot_required


def _initialise_v3_hub_pulse():
    UART_reboot = _check_and_set_serial_config()
    return UART_reboot


def _initialise_v2_hub_pulse():
    if HDMI.set_as_audio_output() is False:
        logger.warning("Failed to configure HDMI output")

    HDMI_reboot = HDMI.set_hdmi_drive_in_boot_config(2)
    UART_reboot = _check_and_set_serial_config()
    I2S_reboot = _check_and_set_I2S_config(False)

    return HDMI_reboot or UART_reboot or I2S_reboot


def _initialise_v1_hub_pulse():
    HDMI_reboot = HDMI.set_hdmi_drive_in_boot_config(2)
    UART_reboot = _check_and_set_serial_config()
    I2S_reboot = _check_and_set_I2S_config(True)

    return HDMI_reboot or UART_reboot or I2S_reboot


#######################
# EXTERNAL OPERATIONS #
#######################


def initialise(host_device_id, device_name="pi-topPULSE"):
    global _host_device_id

    _host_device_id = host_device_id


def reset_device_state(enable):
    """reset_device_state: Deprecated"""
    logger.info(
        "'reset_device_state' function has been deprecated, and can likely be removed. "
        "If you experience problems, please see documentation for instructions."
    )
    return False


def enable_device():
    enabled = False
    reboot_required = False
    v2_hub_hdmi_to_i2s_required = False

    is_pi_top = _host_device_id == DeviceID.pi_top
    is_pi_top_ceed = _host_device_id == DeviceID.pi_top_ceed
    hub_is_v1 = is_pi_top or is_pi_top_ceed
    is_pi_top_3 = _host_device_id == DeviceID.pi_top_3
    is_pi_top_4 = _host_device_id == DeviceID.pi_top_4

    if is_pi_top_3:
        reboot_required = _initialise_v2_hub_pulse()
        if reboot_required is False:
            v2_hub_hdmi_to_i2s_required = True

    elif hub_is_v1 or (_host_device_id == DeviceID.unknown):
        reboot_required = _initialise_v1_hub_pulse()

    elif is_pi_top_4:
        reboot_required = _initialise_v3_hub_pulse()

    else:
        logger.error(
            "Error - unrecognised device ID '"
            + str(_host_device_id)
            + "' - unsure how to initialise pi-topPULSE"
        )

    if reboot_required is False:
        _reset_device_state(True)
        enabled = True

    return enabled, reboot_required, v2_hub_hdmi_to_i2s_required


def disable_device():
    _reset_device_state(False)

    return True


def set_microphone_sample_rate_to_16khz():
    """Set the appropriate I2C bits to enable 16,000Hz recording on the
    microphone."""

    return _update_device_state_bit(_16khz_bit, 1)


def set_microphone_sample_rate_to_22khz():
    """Set the appropriate I2C bits to enable 22,050Hz recording on the
    microphone."""

    return _update_device_state_bit(_16khz_bit, 0)


# GET STATE


def speaker_enabled():
    """Get whether the speaker is enabled."""

    return (_read_device_state() & _get_addr_for_bit(_speaker_bit)) == 0


def mcu_enabled():
    """Get whether the onboard MCU is enabled."""

    return (_read_device_state() & _get_addr_for_bit(_mcu_bit)) == 0


def eeprom_enabled():
    """Get whether the eeprom is enabled."""

    return (_read_device_state() & _get_addr_for_bit(_eeprom_bit)) != 0


def microphone_sample_rate_is_16khz():
    """Get whether the microphone is set to record at a sample rate of
    16,000Hz."""

    return (_read_device_state() & _get_addr_for_bit(_16khz_bit)) != 0


def microphone_sample_rate_is_22khz():
    """Get whether the microphone is set to record at a sample rate of
    22,050Hz."""

    return (_read_device_state() & _get_addr_for_bit(_16khz_bit)) == 0
