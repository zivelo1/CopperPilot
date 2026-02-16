# KiCad Converter - Modular Architecture v10.0

## Overview
Professional KiCad converter with modular pipeline architecture for converting circuit JSON files to KiCad format.

## Architecture

### Pipeline Stages
1. **InputProcessor** - Parse and validate JSON circuit files
2. **ComponentProcessor** - Map components to KiCad symbols/footprints
3. **LayoutEngine** - Generate schematic and PCB layouts
4. **NetlistGenerator** - Build circuit connectivity
5. **Router** - Route wires and PCB tracks
6. **OutputGenerator** - Create KiCad files (.kicad_pro, .kicad_sch, .kicad_pcb)
7. **Validator** - Run ERC/DRC checks and generate reports

### Directory Structure
```
kicad/
├── modules/           # Pipeline stage implementations
│   ├── input_processor.py
│   ├── component_processor.py
│   ├── layout_engine.py
│   ├── netlist_generator.py
│   ├── router.py
│   ├── output_generator.py
│   └── validator.py
├── utils/            # Base classes and utilities
│   └── base.py
├── data/             # Component and pin databases
│   ├── component_db.json
│   └── pin_mappings.json
├── config/           # Configuration settings
│   └── settings.json
└── README.md
```

## Usage

### Command Line
```bash
python3 kicad_converter.py <input_folder> <output_folder>
```

### Example
```bash
cd output/project-folder
python3 ../../scripts/kicad_converter.py lowlevel kicad
```

## Features

### Component Support
- **Passive:** Resistors, Capacitors, Inductors
- **Semiconductors:** Diodes, LEDs, Transistors, MOSFETs
- **ICs:** Op-amps, Regulators, Microcontrollers
- **Connectors:** Headers, Terminal blocks
- **Power:** Transformers, Fuses, Varistors
- **Other:** Crystals, Test points

### Symbol/Footprint Mapping
- Automatic selection based on component type
- Package-aware footprint selection
- Fallback mechanisms for unknown components
- Support for both SMD and THT packages

### Layout Generation
- Hierarchical component grouping
- Grid-based placement
- Signal flow optimization (left-to-right)
- Separate schematic and PCB layouts

### Routing
- Manhattan (orthogonal) routing
- Star topology for multi-point nets
- Junction dots at connections
- PCB track width based on net class

### Validation
- **ERC:** Electrical Rules Check
  - Unconnected pins detection
  - Floating net detection
  - Power/ground verification
  - Duplicate connection detection

- **DRC:** Design Rules Check
  - Component overlap detection
  - Track width compliance
  - Board dimension checks

### Error Handling
- Graceful degradation
- Comprehensive error reporting
- Fallback mechanisms for each stage
- Detailed validation reports

## Configuration

Edit `config/settings.json` to customize:
- Grid sizes
- Track widths
- Via sizes
- Clearances
- Text sizes
- Layer definitions
- Routing algorithms

## Output Files

### Generated Files
- `project.kicad_pro` - Project configuration
- `project.kicad_sch` - Schematic design
- `project.kicad_pcb` - PCB layout
- `conversion_report.json` - Detailed conversion report
- `validation_report.txt` - ERC/DRC results

### File Compatibility
- KiCad 8.0+ (version 20230121)
- S-expression format
- Standard KiCad libraries

## Performance
- 60 components: < 0.02 seconds
- 100+ components: < 0.1 seconds
- Memory efficient processing

## Error Recovery
Each stage implements fallback strategies:
- Unknown components → Generic symbols
- Missing footprints → Default packages
- Routing failures → Straight lines
- Validation errors → Detailed reports

## Development

### Adding New Components
1. Edit `data/component_db.json`
2. Add symbol and footprint mappings
3. Update pin mappings if needed

### Extending Pipeline
1. Create new module in `modules/`
2. Inherit from `PipelineStage`
3. Implement `process()` method
4. Add to pipeline in main script

## Troubleshooting

### Common Issues
- **No JSON files found:** Check input folder path
- **Unknown component type:** Add to component database
- **Pin mapping errors:** Update pin_mappings.json
- **Validation failures:** Check input data for conflicts

### Debug Mode
Set logging level to DEBUG in main script:
```python
logging.basicConfig(level=logging.DEBUG)
```

## Version History
- v10.0 (Jan 2025) - Complete modular rewrite
- v9.0 (Sep 2024) - Monolithic implementation
- v8.0 (Sep 2024) - Pin mapping fixes

## License
Part of Circuit Design Automation System