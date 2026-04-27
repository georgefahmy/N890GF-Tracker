import xml.etree.ElementTree as ET
from datetime import datetime
from xml.dom import minidom


def create_vpx_config():
    # 1. Root Element with Namespaces
    root = ET.Element("VpxConfiguration")
    root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
    root.set("xmlns:xsd", "http://www.w3.org/2001/XMLSchema")

    # 2. Header Information
    ET.SubElement(root, "User").text = "George Fahmy"
    ET.SubElement(root, "TailNumber").text = "N890GF"
    ET.SubElement(root, "HardwareVersion").text = "2"
    ET.SubElement(root, "SoftwareMajor").text = "1"
    ET.SubElement(root, "SoftwareMinor").text = "6"
    ET.SubElement(root, "ConfiguratorVersion").text = "1.6.0.0"

    # 3. Circuit Definitions
    # Format: (ID, Breaker, Fault, Switch, Enabled, Name)
    circuits = [
        ("Starter", 10, "false", "AlwaysOn", "true", "Starter"),
        ("EFIS", 5, "false", "AlwaysOn", "true", "EFIS PFD"),
        ("Alternator", 5, "false", "Switch1", "true", "Alternator Field"),
        ("A5_1", 5, "true", "Switch4", "true", "Boost pump"),
        ("A5_2", 2, "false", "Switch3", "true", "SV-INT-2S - BOSE"),
        ("A5_3", 2, "false", "Switch3", "true", "Garmin G5"),
        ("A5_4", 3, "false", "Switch9", "true", "E-Mag/P-Mag 1"),
        ("A5_5", 3, "false", "Switch10", "true", "E-Mag/P-Mag 2"),
        ("A5_6", 5, "false", "Switch6", "true", "Taxi Light Left"),
        ("A5_7", 5, "true", "Switch6", "true", "Taxi Light Right"),
        ("A5_8", 2, "false", "Switch3", "true", "Hobbs meter"),
        ("A5_9", 3, "false", "Switch3", "true", "SV-XPNDR/SV-ADSB"),
        ("A5_10", 5, "true", "Switch7", "true", "Nav Light Left"),
        ("A5_11", 5, "false", "Switch3", "true", "EFIS MFD"),
        ("A5_12", 5, "true", "Switch7", "true", "Nav Light Right"),
        ("A5_13", 1, "false", "AlwaysOff", "false", "Reserved"),
        ("A10_1", 5, "true", "Switch3", "true", "trim AP Power"),
        ("A10_2", 7, "true", "Switch5", "true", "Left Landing Lt"),
        ("A10_3", 7, "true", "Switch5", "true", "Right Landing Lt"),
        ("A10_4", 7, "true", "Switch8", "true", "Strobe Left"),
        ("A10_5", 7, "true", "Switch8", "true", "Strobe Right"),
        ("A10_6", 7, "false", "Switch3", "true", "SV-COM-X25"),
        ("A15_1", 10, "false", "Switch3", "true", "AP Servos"),
        ("A15_2", 7, "false", "AlwaysOff", "false", "Reserved"),
        ("A15_3", 10, "true", "AlwaysOn", "true", "Eyeball lights"),
        ("A3_1", 1, "false", "AlwaysOn", "true", "ELT"),
        ("A2_1", 1, "false", "AlwaysOff", "false", ""),
        ("A2_2", 2, "false", "AlwaysOff", "false", ""),
    ]

    circuit_configs = ET.SubElement(root, "CircuitConfigurations")
    for c_id, breaker, fault, sw_id, enabled, name in circuits:
        cc = ET.SubElement(circuit_configs, "CircuitConfiguration")
        ET.SubElement(cc, "Id").text = str(c_id)
        ET.SubElement(cc, "BreakerValue").text = str(breaker)
        ET.SubElement(cc, "CurrentFault").text = str(fault)
        ET.SubElement(cc, "SwitchId").text = str(sw_id)
        ET.SubElement(cc, "Enabled").text = str(enabled)
        ET.SubElement(cc, "Name").text = str(name)

    # 4. System & Hardware Settings
    ET.SubElement(root, "Sport").text = "false"

    sys_config = ET.SubElement(root, "SystemConfiguration")
    ET.SubElement(sys_config, "VoltageLimit").text = "Volts16"
    ET.SubElement(sys_config, "SecondaryAlternator").text = "NoCircuit"

    wigwag = ET.SubElement(root, "WigWagConfiguration")
    ET.SubElement(wigwag, "Device1").text = "NoCircuit"
    ET.SubElement(wigwag, "Device2").text = "NoCircuit"
    ET.SubElement(wigwag, "WarmUpPeriod").text = "7"
    ET.SubElement(wigwag, "Speed").text = "77"

    # 5. Control Surfaces (Trim & Flaps)
    pitch = ET.SubElement(root, "PitchTrimConfiguration")
    pitch_data = {
        "Type": "Pitch",
        "Enabled": "false",
        "ReversePolarity": "true",
        "UpEndpoint": "5",
        "DownEndpoint": "255",
        "NeutralPoint": "55",
        "Power": "55",
        "Speed": "155",
    }
    for k, v in pitch_data.items():
        ET.SubElement(pitch, k).text = v

    roll = ET.SubElement(root, "RollTrimConfiguration")
    roll_data = {
        "Type": "Roll",
        "Enabled": "false",
        "ReversePolarity": "false",
        "UpEndpoint": "0",
        "DownEndpoint": "255",
        "NeutralPoint": "0",
        "Power": "0",
        "Speed": "0",
    }
    for k, v in roll_data.items():
        ET.SubElement(roll, k).text = v

    flaps = ET.SubElement(root, "FlapConfiguration")
    flap_data = {
        "Type": "Momentary",
        "Enabled": "true",
        "ReversePolarity": "false",
        "UpEndpoint": "0",
        "DownEndpoint": "255",
        "MidPoint1": "0",
        "MidPoint2": "0",
        "BreakerValue": "5",
        "MaxSpeed": "0",
        "OverspeedPosition": "0",
        "EndDuration": "0.5",
    }
    for k, v in flap_data.items():
        ET.SubElement(flaps, k).text = v

    # 6. Final Boilerplate
    ET.SubElement(root, "ContinuousFlaps").text = "false"
    ET.SubElement(root, "FlapReflex").text = "false"
    ET.SubElement(root, "FlapSlowRetract").text = "false"
    ET.SubElement(root, "FlapSlowRetractHighRpm").text = "false"

    # Dynamic Timestamp
    ET.SubElement(root, "TimeStamp").text = datetime.now().isoformat()

    # 7. Pretty Print and Save
    xml_str = ET.tostring(root, encoding="utf-8")
    parsed_str = minidom.parseString(xml_str)
    pretty_xml = parsed_str.toprettyxml(indent="  ")

    filename = f"VPX_Config_N890GF_{datetime.now().strftime('%Y%m%d')}.xml"
    with open(filename, "w", encoding="utf-8") as f:
        # Remove the extra default XML declaration line from minidom if desired
        f.write(pretty_xml)

    print(f"Success: Configuration saved to {filename}")


if __name__ == "__main__":
    create_vpx_config()
