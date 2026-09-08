## 1. INGESTION (Hand-Written CFG)

**Instruction:** Parse the user's `.cfg` text for blocks matching the syntax below. 
**Component ID Format:** `[component_prefix]_[identifier]`

**Expected Syntax:**
```cfg
[Component Type] [Component ID] {
    [Parameter 1]: [Type] // [Description & Constraints]
    [Parameter 2]: [Type] // [Description & Constraints]
}
```

## 2. UI ABSTRACTION (hardware.json)

```json
{
  "id": "<Component ID>",
  "type": "<Component Type>",
  "ui_group": "<UI Category Tab>",
  "parameters": {
    "<parameter_1>": { "type": "<data_type>", "value": "<parsed_value>" },
    "<parameter_2>": { "type": "<data_type>", "value": "<parsed_value>" }
  },
  "computed": {
    "<computed_var_1>": { "type": "<data_type>", "formula": "<math_or_logic_expression>" }
  }
}
```
## 3. COMPILATION (INI & HAL)

machine.ini
```ini
[SECTION_NAME]
PARAMETER_NAME = <parameters.parameter_1>
COMPUTED_NAME = <computed.computed_var_1>
```

machine.hal
```hal
# Component: <id>
loadrt <required_module> names=<id>
addf <module_function> <thread_name>

setp <module_pin> <parameters.parameter_1>
net <id>-signal <source_pin> => <target_pin>
```
webgui_connections.hal
```hal
# UI Bindings for <id>
net <id>-ui-signal <halui_pin> => <ui_pin>
```