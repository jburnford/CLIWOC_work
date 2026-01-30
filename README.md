# CLIWOC Trade Network Visualizations

Interactive visualizations of global maritime trade routes from 1750-1850, based on the CLIWOC (Climatological Database for the World's Oceans) ship logbook data.

## Live Visualizations

- **[Port Map](https://jburnford.github.io/CLIWOC_work/cliwoc_ports_map.html)** - 799 ports extracted from 287,114 ship logbook records
- **[Trade Network](https://jburnford.github.io/CLIWOC_work/cliwoc_trade_network.html)** - 1,013 trade routes showing voyage patterns, with slave trade routes highlighted in red

## Data Source

**CLIWOC 2.1** - Climatological Database for the World's Oceans
- 287,114 logbook records from Dutch, British, Spanish, and French ships
- Time period: 1750-1850
- Original data: [KNMI](https://www.knmi.nl/)
- Reformatted version: [Steven Ottens](https://stvno.github.io/page/cliwoc/)
- Background: [Historical Climatology](https://www.historicalclimatology.com/cliwoc.html)

## Key Findings

### Top Trade Corridors
| Route | Voyages |
|-------|---------|
| Montevideo ↔ La Coruña | 17,255 |
| La Coruña ↔ La Habana | 13,554 |
| Rotterdam ↔ Batavia | 13,118 |
| Nieuwediep ↔ Batavia | 9,933 |

### Data Composition
| Nationality | Records | % |
|-------------|---------|---|
| Dutch | 126,402 | 44% |
| British | 94,859 | 33% |
| Spanish | 54,115 | 19% |
| French | 10,631 | 4% |

### Slave Trade Routes
The dataset contains ~60 routes involving African ports (~5,300 voyages), primarily Dutch trade from Elmina/Guinea to Suriname. However, CLIWOC **underrepresents the transatlantic slave trade** because:
- Data comes from naval and East India Company logbooks
- Private merchant slave ship records were often not preserved
- British records post-1807 abolition are limited

For comprehensive slave trade analysis, combine with the [Trans-Atlantic Slave Trade Database](https://slavevoyages.org/) (36,000+ documented voyages).

## Files

| File | Description |
|------|-------------|
| `cliwoc_ports_map.html` | Interactive port visualization |
| `cliwoc_trade_network.html` | Interactive trade route network |
| `cliwoc_ports_map.png` | Static port map image |
| `all_ports_geocoded.csv` | 813 ports with coordinates |
| `trade_routes.csv` | 2,874 unique trade routes |
| `trade_routes_geocoded.csv` | 1,013 routes with coordinates |

## Data Processing

Ports were geocoded using:
1. Coordinates from anchored ship observations in CLIWOC
2. Manual historical gazetteer mapping (e.g., "Batavia" → Jakarta)

## License

CLIWOC data is freely available for research use. Visualizations created by Jim Clifford and Claude.
