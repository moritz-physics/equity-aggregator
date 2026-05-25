"""S&P 500 index adapter (503 constituents).

Aggregates per-constituent data from:

  - **yfinance** — unofficial Yahoo Finance scraper. Used for price,
    currency, sector, beta, market cap, dividend yield, ex-dividend date.
  - **Static curated map** — ``SP500_MEMBERS`` below. Source of truth for
    the constituent set, names, and ISINs.

Exploration findings (live probes, 2026-05-24):

  * ``yf.Ticker(t).info["isin"]`` is ``None`` for every US ticker probed.
    yfinance does not surface ISINs for US listings.
  * OpenFIGI's ``/v3/mapping`` endpoint returns FIGI but never ISIN — and
    its free tier is 25 req / 6 s, which 500 concurrent calls would
    saturate immediately. We therefore skip OpenFIGI for S&P 500
    (unlike DAX/SMI where the index is small enough to absorb the cost).
  * Wikipedia *used to* publish a CUSIP column on the S&P 500 page; this
    column was removed in 2024. The page is no longer a viable ISIN
    source.

ISIN sourcing — **SSGA SPY holdings → CUSIP → ISIN**:

  * State Street publishes the daily holdings of the SPDR S&P 500 ETF
    (SPY) as a free xlsx that includes a 9-char ``Identifier`` (CUSIP)
    per row. SPY tracks the full S&P 500, so its holdings == the
    constituent set.
  * We convert CUSIP → ISIN with the standard ISO 6166 check-digit
    algorithm (US prefix + 9-char CUSIP + 1 check digit; letters A-Z map
    to 10-35; rightmost digit doubled, sum digits-of-products mod 10).
    Verified against known ISINs: AAPL→US0378331005, MSFT→US5949181045,
    NVDA→US67066G1040.
  * For US-listed shares of foreign issuers (G-/H-/N-/V-prefix CUSIPs,
    aka CINS codes), the resulting ``US...`` ISIN is the canonical
    identifier for the *US listing*, not the issuer's domicile ISIN
    (e.g. ACN → USG1151C1011 for the NYSE listing; Accenture's Irish
    ISIN IE00B4BNMY34 refers to the same equity in Ireland).

  Regenerate ``SP500_MEMBERS`` after every S&P quarterly rebalance:

      uv run python scripts/gen_sp500_isins.py

  …and paste the output between the BEGIN/END markers below.

⚠️  yfinance is **unofficial**. Yahoo changes endpoints, field shapes, and
    rate limits without notice. Cache aggressively, fail loudly on schema
    drift, and never use this as a system of record.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, cast

from equity_aggregator.adapters.base import IndexAdapter
from equity_aggregator.core.models import Constituent, Index

logger = logging.getLogger(__name__)

SOURCE_LABEL = "yfinance (unofficial)"
INDEX_NAME = "S&P 500"
INDEX_COUNTRY = "US"


@dataclass(frozen=True, slots=True)
class _Member:
    ticker: str
    name: str
    isin: str
    weight: float | None = None  # filled when authoritative source provides it


# ---------------------------------------------------------------------------
# BEGIN GENERATED — scripts/gen_sp500_isins.py
# Regenerate via:  uv run python scripts/gen_sp500_isins.py
# Source:          SSGA SPY holdings (State Street SPDR S&P 500 ETF)
# ---------------------------------------------------------------------------
SP500_MEMBERS: tuple[_Member, ...] = (
    _Member("A", "AGILENT TECHNOLOGIES INC", "US00846U1016"),
    _Member("AAPL", "APPLE INC", "US0378331005"),
    _Member("ABBV", "ABBVIE INC", "US00287Y1091"),
    _Member("ABNB", "AIRBNB INC CLASS A", "US0090661010"),
    _Member("ABT", "ABBOTT LABORATORIES", "US0028241000"),
    _Member("ACGL", "ARCH CAPITAL GROUP LTD", "USG0450A1054"),
    _Member("ACN", "ACCENTURE PLC CL A", "USG1151C1011"),
    _Member("ADBE", "ADOBE INC", "US00724F1012"),
    _Member("ADI", "ANALOG DEVICES INC", "US0326541051"),
    _Member("ADM", "ARCHER DANIELS MIDLAND CO", "US0394831020"),
    _Member("ADP", "AUTOMATIC DATA PROCESSING", "US0530151036"),
    _Member("ADSK", "AUTODESK INC", "US0527691069"),
    _Member("AEE", "AMEREN CORPORATION", "US0236081024"),
    _Member("AEP", "AMERICAN ELECTRIC POWER", "US0255371017"),
    _Member("AES", "AES CORP", "US00130H1059"),
    _Member("AFL", "AFLAC INC", "US0010551028"),
    _Member("AIG", "AMERICAN INTERNATIONAL GROUP", "US0268747849"),
    _Member("AIZ", "ASSURANT INC", "US04621X1081"),
    _Member("AJG", "ARTHUR J GALLAGHER + CO", "US3635761097"),
    _Member("AKAM", "AKAMAI TECHNOLOGIES INC", "US00971T1016"),
    _Member("ALB", "ALBEMARLE CORP", "US0126531013"),
    _Member("ALGN", "ALIGN TECHNOLOGY INC", "US0162551016"),
    _Member("ALL", "ALLSTATE CORP", "US0200021014"),
    _Member("ALLE", "ALLEGION PLC", "USG0176J1090"),
    _Member("AMAT", "APPLIED MATERIALS INC", "US0382221051"),
    _Member("AMCR", "AMCOR PLC", "USG0250X1497"),
    _Member("AMD", "ADVANCED MICRO DEVICES", "US0079031078"),
    _Member("AME", "AMETEK INC", "US0311001004"),
    _Member("AMGN", "AMGEN INC", "US0311621009"),
    _Member("AMP", "AMERIPRISE FINANCIAL INC", "US03076C1062"),
    _Member("AMT", "AMERICAN TOWER CORP", "US03027X1000"),
    _Member("AMZN", "AMAZON.COM INC", "US0231351067"),
    _Member("ANET", "ARISTA NETWORKS INC", "US0404132054"),
    _Member("AON", "AON PLC CLASS A", "USG0403H1089"),
    _Member("AOS", "SMITH (A.O.) CORP", "US8318652091"),
    _Member("APA", "APA CORP", "US03743Q1085"),
    _Member("APD", "AIR PRODUCTS + CHEMICALS INC", "US0091581068"),
    _Member("APH", "AMPHENOL CORP CL A", "US0320951017"),
    _Member("APO", "APOLLO GLOBAL MANAGEMENT INC", "US03769M1062"),
    _Member("APP", "APPLOVIN CORP CLASS A", "US03831W1080"),
    _Member("APTV", "APTIV PLC", "USG3265R1070"),
    _Member("ARE", "ALEXANDRIA REAL ESTATE EQUIT", "US0152711091"),
    _Member("ARES", "ARES MANAGEMENT CORP   A", "US03990B1017"),
    _Member("ATO", "ATMOS ENERGY CORP", "US0495601058"),
    _Member("AVB", "AVALONBAY COMMUNITIES INC", "US0534841012"),
    _Member("AVGO", "BROADCOM INC", "US11135F1012"),
    _Member("AVY", "AVERY DENNISON CORP", "US0536111091"),
    _Member("AWK", "AMERICAN WATER WORKS CO INC", "US0304201033"),
    _Member("AXON", "AXON ENTERPRISE INC", "US05464C1018"),
    _Member("AXP", "AMERICAN EXPRESS CO", "US0258161092"),
    _Member("AZO", "AUTOZONE INC", "US0533321024"),
    _Member("BA", "BOEING CO/THE", "US0970231058"),
    _Member("BAC", "BANK OF AMERICA CORP", "US0605051046"),
    _Member("BALL", "BALL CORP", "US0584981064"),
    _Member("BAX", "BAXTER INTERNATIONAL INC", "US0718131099"),
    _Member("BBY", "BEST BUY CO INC", "US0865161014"),
    _Member("BDX", "BECTON DICKINSON AND CO", "US0758871091"),
    _Member("BEN", "FRANKLIN RESOURCES INC", "US3546131018"),
    _Member("BF-B", "BROWN FORMAN CORP CLASS B", "US1156372096"),
    _Member("BG", "BUNGE GLOBAL SA", "USH113561049"),
    _Member("BIIB", "BIOGEN INC", "US09062X1037"),
    _Member("BKNG", "BOOKING HOLDINGS INC", "US09857L1089"),
    _Member("BKR", "BAKER HUGHES CO", "US05722G1004"),
    _Member("BLDR", "BUILDERS FIRSTSOURCE INC", "US12008R1077"),
    _Member("BLK", "BLACKROCK INC", "US09290D1019"),
    _Member("BMY", "BRISTOL MYERS SQUIBB CO", "US1101221083"),
    _Member("BNY", "BANK OF NEW YORK MELLON CORP", "US0640581007"),
    _Member("BR", "BROADRIDGE FINANCIAL SOLUTIO", "US11133T1034"),
    _Member("BRK-B", "BERKSHIRE HATHAWAY INC CL B", "US0846707026"),
    _Member("BRO", "BROWN + BROWN INC", "US1152361010"),
    _Member("BSX", "BOSTON SCIENTIFIC CORP", "US1011371077"),
    _Member("BX", "BLACKSTONE INC", "US09260D1072"),
    _Member("BXP", "BXP INC", "US1011211018"),
    _Member("C", "CITIGROUP INC", "US1729674242"),
    _Member("CAG", "CONAGRA BRANDS INC", "US2058871029"),
    _Member("CAH", "CARDINAL HEALTH INC", "US14149Y1082"),
    _Member("CARR", "CARRIER GLOBAL CORP", "US14448C1045"),
    _Member("CASY", "CASEY S GENERAL STORES INC", "US1475281036"),
    _Member("CAT", "CATERPILLAR INC", "US1491231015"),
    _Member("CB", "CHUBB LTD", "USH1467J1046"),
    _Member("CBOE", "CBOE GLOBAL MARKETS INC", "US12503M1080"),
    _Member("CBRE", "CBRE GROUP INC   A", "US12504L1098"),
    _Member("CCI", "CROWN CASTLE INC", "US22822V1017"),
    _Member("CCL", "CARNIVAL CORP LTD", "USG2004J1037"),
    _Member("CDNS", "CADENCE DESIGN SYS INC", "US1273871087"),
    _Member("CDW", "CDW CORP/DE", "US12514G1085"),
    _Member("CEG", "CONSTELLATION ENERGY", "US21037T1097"),
    _Member("CF", "CF INDUSTRIES HOLDINGS INC", "US1252691001"),
    _Member("CFG", "CITIZENS FINANCIAL GROUP", "US1746101054"),
    _Member("CHD", "CHURCH + DWIGHT CO INC", "US1713401024"),
    _Member("CHRW", "C.H. ROBINSON WORLDWIDE INC", "US12541W2098"),
    _Member("CHTR", "CHARTER COMMUNICATIONS INC A", "US16119P1084"),
    _Member("CI", "THE CIGNA GROUP", "US1255231003"),
    _Member("CIEN", "CIENA CORP", "US1717793095"),
    _Member("CINF", "CINCINNATI FINANCIAL CORP", "US1720621010"),
    _Member("CL", "COLGATE PALMOLIVE CO", "US1941621039"),
    _Member("CLX", "CLOROX COMPANY", "US1890541097"),
    _Member("CMCSA", "COMCAST CORP CLASS A", "US20030N1019"),
    _Member("CME", "CME GROUP INC", "US12572Q1058"),
    _Member("CMG", "CHIPOTLE MEXICAN GRILL INC", "US1696561059"),
    _Member("CMI", "CUMMINS INC", "US2310211063"),
    _Member("CMS", "CMS ENERGY CORP", "US1258961002"),
    _Member("CNC", "CENTENE CORP", "US15135B1017"),
    _Member("CNP", "CENTERPOINT ENERGY INC", "US15189T1079"),
    _Member("COF", "CAPITAL ONE FINANCIAL CORP", "US14040H1059"),
    _Member("COHR", "COHERENT CORP", "US19247G1076"),
    _Member("COIN", "COINBASE GLOBAL INC  CLASS A", "US19260Q1076"),
    _Member("COO", "COOPER COS INC/THE", "US2166485019"),
    _Member("COP", "CONOCOPHILLIPS", "US20825C1045"),
    _Member("COR", "CENCORA INC", "US03073E1055"),
    _Member("COST", "COSTCO WHOLESALE CORP", "US22160K1051"),
    _Member("CPAY", "CORPAY INC", "US2199481068"),
    _Member("CPB", "THE CAMPBELL S COMPANY", "US1344291091"),
    _Member("CPRT", "COPART INC", "US2172041061"),
    _Member("CPT", "CAMDEN PROPERTY TRUST", "US1331311027"),
    _Member("CRH", "CRH PLC", "USG255081055"),
    _Member("CRL", "CHARLES RIVER LABORATORIES", "US1598641074"),
    _Member("CRM", "SALESFORCE INC", "US79466L3024"),
    _Member("CRWD", "CROWDSTRIKE HOLDINGS INC   A", "US22788C1053"),
    _Member("CSCO", "CISCO SYSTEMS INC", "US17275R1023"),
    _Member("CSGP", "COSTAR GROUP INC", "US22160N1090"),
    _Member("CSX", "CSX CORP", "US1264081035"),
    _Member("CTAS", "CINTAS CORP", "US1729081059"),
    _Member("CTSH", "COGNIZANT TECH SOLUTIONS A", "US1924461023"),
    _Member("CTVA", "CORTEVA INC", "US22052L1044"),
    _Member("CVNA", "CARVANA CO", "US1468691027"),
    _Member("CVS", "CVS HEALTH CORP", "US1266501006"),
    _Member("CVX", "CHEVRON CORP", "US1667641005"),
    _Member("D", "DOMINION ENERGY INC", "US25746U1097"),
    _Member("DAL", "DELTA AIR LINES INC", "US2473617023"),
    _Member("DASH", "DOORDASH INC   A", "US25809K1051"),
    _Member("DD", "DUPONT DE NEMOURS INC", "US26614N1028"),
    _Member("DDOG", "DATADOG INC   CLASS A", "US23804L1035"),
    _Member("DE", "DEERE + CO", "US2441991054"),
    _Member("DECK", "DECKERS OUTDOOR CORP", "US2435371073"),
    _Member("DELL", "DELL TECHNOLOGIES  C", "US24703L2025"),
    _Member("DG", "DOLLAR GENERAL CORP", "US2566771059"),
    _Member("DGX", "QUEST DIAGNOSTICS INC", "US74834L1008"),
    _Member("DHI", "DR HORTON INC", "US23331A1097"),
    _Member("DHR", "DANAHER CORP", "US2358511028"),
    _Member("DIS", "WALT DISNEY CO/THE", "US2546871060"),
    _Member("DLR", "DIGITAL REALTY TRUST INC", "US2538681030"),
    _Member("DLTR", "DOLLAR TREE INC", "US2567461080"),
    _Member("DOC", "HEALTHPEAK PROPERTIES INC", "US42250P1030"),
    _Member("DOV", "DOVER CORP", "US2600031080"),
    _Member("DOW", "DOW INC", "US2605571031"),
    _Member("DPZ", "DOMINO S PIZZA INC", "US25754A2015"),
    _Member("DRI", "DARDEN RESTAURANTS INC", "US2371941053"),
    _Member("DTE", "DTE ENERGY COMPANY", "US2333311072"),
    _Member("DUK", "DUKE ENERGY CORP", "US26441C2044"),
    _Member("DVA", "DAVITA INC", "US23918K1088"),
    _Member("DVN", "DEVON ENERGY CORP", "US25179M1036"),
    _Member("DXCM", "DEXCOM INC", "US2521311074"),
    _Member("EA", "ELECTRONIC ARTS INC", "US2855121099"),
    _Member("EBAY", "EBAY INC", "US2786421030"),
    _Member("ECL", "ECOLAB INC", "US2788651006"),
    _Member("ED", "CONSOLIDATED EDISON INC", "US2091151041"),
    _Member("EFX", "EQUIFAX INC", "US2944291051"),
    _Member("EG", "EVEREST GROUP LTD", "USG3223R1089"),
    _Member("EIX", "EDISON INTERNATIONAL", "US2810201077"),
    _Member("EL", "ESTEE LAUDER COMPANIES CL A", "US5184391044"),
    _Member("ELV", "ELEVANCE HEALTH INC", "US0367521038"),
    _Member("EME", "EMCOR GROUP INC", "US29084Q1004"),
    _Member("EMR", "EMERSON ELECTRIC CO", "US2910111044"),
    _Member("EOG", "EOG RESOURCES INC", "US26875P1012"),
    _Member("EPAM", "EPAM SYSTEMS INC", "US29414B1044"),
    _Member("EQIX", "EQUINIX INC", "US29444U7000"),
    _Member("EQR", "EQUITY RESIDENTIAL", "US29476L1070"),
    _Member("EQT", "EQT CORP", "US26884L1098"),
    _Member("ERIE", "ERIE INDEMNITY COMPANY CL A", "US29530P1021"),
    _Member("ES", "EVERSOURCE ENERGY", "US30040W1080"),
    _Member("ESS", "ESSEX PROPERTY TRUST INC", "US2971781057"),
    _Member("ETN", "EATON CORP PLC", "USG291831034"),
    _Member("ETR", "ENTERGY CORP", "US29364G1031"),
    _Member("EVRG", "EVERGY INC", "US30034W1062"),
    _Member("EW", "EDWARDS LIFESCIENCES CORP", "US28176E1082"),
    _Member("EXC", "EXELON CORP", "US30161N1019"),
    _Member("EXE", "EXPAND ENERGY CORP", "US1651677353"),
    _Member("EXPD", "EXPEDITORS INTL WASH INC", "US3021301094"),
    _Member("EXPE", "EXPEDIA GROUP INC", "US30212P3038"),
    _Member("EXR", "EXTRA SPACE STORAGE INC", "US30225T1025"),
    _Member("F", "FORD MOTOR CO", "US3453708600"),
    _Member("FANG", "DIAMONDBACK ENERGY INC", "US25278X1090"),
    _Member("FAST", "FASTENAL CO", "US3119001044"),
    _Member("FCX", "FREEPORT MCMORAN INC", "US35671D8570"),
    _Member("FDS", "FACTSET RESEARCH SYSTEMS INC", "US3030751057"),
    _Member("FDX", "FEDEX CORP", "US31428X1063"),
    _Member("FE", "FIRSTENERGY CORP", "US3379321074"),
    _Member("FFIV", "F5 INC", "US3156161024"),
    _Member("FICO", "FAIR ISAAC CORP", "US3032501047"),
    _Member("FIS", "FIDELITY NATIONAL INFO SERV", "US31620M1062"),
    _Member("FISV", "FISERV INC", "US3377381088"),
    _Member("FITB", "FIFTH THIRD BANCORP", "US3167731005"),
    _Member("FIX", "COMFORT SYSTEMS USA INC", "US1999081045"),
    _Member("FOX", "FOX CORP   CLASS B", "US35137L2043"),
    _Member("FOXA", "FOX CORP   CLASS A", "US35137L1052"),
    _Member("FRT", "FEDERAL REALTY INVS TRUST", "US3137451015"),
    _Member("FSLR", "FIRST SOLAR INC", "US3364331070"),
    _Member("FTNT", "FORTINET INC", "US34959E1091"),
    _Member("FTV", "FORTIVE CORP", "US34959J1088"),
    _Member("GD", "GENERAL DYNAMICS CORP", "US3695501086"),
    _Member("GDDY", "GODADDY INC   CLASS A", "US3802371076"),
    _Member("GE", "GENERAL ELECTRIC", "US3696043013"),
    _Member("GEHC", "GE HEALTHCARE TECHNOLOGY", "US36266G1076"),
    _Member("GEN", "GEN DIGITAL INC", "US6687711084"),
    _Member("GEV", "GE VERNOVA INC", "US36828A1016"),
    _Member("GILD", "GILEAD SCIENCES INC", "US3755581036"),
    _Member("GIS", "GENERAL MILLS INC", "US3703341046"),
    _Member("GL", "GLOBE LIFE INC", "US37959E1029"),
    _Member("GLW", "CORNING INC", "US2193501051"),
    _Member("GM", "GENERAL MOTORS CO", "US37045V1008"),
    _Member("GNRC", "GENERAC HOLDINGS INC", "US3687361044"),
    _Member("GOOG", "ALPHABET INC CL C", "US02079K1079"),
    _Member("GOOGL", "ALPHABET INC CL A", "US02079K3059"),
    _Member("GPC", "GENUINE PARTS CO", "US3724601055"),
    _Member("GPN", "GLOBAL PAYMENTS INC", "US37940X1028"),
    _Member("GRMN", "GARMIN LTD", "USH2906T1090"),
    _Member("GS", "GOLDMAN SACHS GROUP INC", "US38141G1040"),
    _Member("GWW", "WW GRAINGER INC", "US3848021040"),
    _Member("HAL", "HALLIBURTON CO", "US4062161017"),
    _Member("HAS", "HASBRO INC", "US4180561072"),
    _Member("HBAN", "HUNTINGTON BANCSHARES INC", "US4461501045"),
    _Member("HCA", "HCA HEALTHCARE INC", "US40412C1018"),
    _Member("HD", "HOME DEPOT INC", "US4370761029"),
    _Member("HIG", "HARTFORD INSURANCE GROUP INC", "US4165151048"),
    _Member("HII", "HUNTINGTON INGALLS INDUSTRIE", "US4464131063"),
    _Member("HLT", "HILTON WORLDWIDE HOLDINGS IN", "US43300A2033"),
    _Member("HON", "HONEYWELL INTERNATIONAL INC", "US4385161066"),
    _Member("HOOD", "ROBINHOOD MARKETS INC   A", "US7707001027"),
    _Member("HPE", "HEWLETT PACKARD ENTERPRISE", "US42824C1099"),
    _Member("HPQ", "HP INC", "US40434L1052"),
    _Member("HRL", "HORMEL FOODS CORP", "US4404521001"),
    _Member("HSIC", "HENRY SCHEIN INC", "US8064071025"),
    _Member("HST", "HOST HOTELS + RESORTS INC", "US44107P1049"),
    _Member("HSY", "HERSHEY CO/THE", "US4278661081"),
    _Member("HUBB", "HUBBELL INC", "US4435106079"),
    _Member("HUM", "HUMANA INC", "US4448591028"),
    _Member("HWM", "HOWMET AEROSPACE INC", "US4432011082"),
    _Member("IBKR", "INTERACTIVE BROKERS GRO CL A", "US45841N1072"),
    _Member("IBM", "INTL BUSINESS MACHINES CORP", "US4592001014"),
    _Member("ICE", "INTERCONTINENTAL EXCHANGE IN", "US45866F1049"),
    _Member("IDXX", "IDEXX LABORATORIES INC", "US45168D1046"),
    _Member("IEX", "IDEX CORP", "US45167R1041"),
    _Member("IFF", "INTL FLAVORS + FRAGRANCES", "US4595061015"),
    _Member("INCY", "INCYTE CORP", "US45337C1027"),
    _Member("INTC", "INTEL CORP", "US4581401001"),
    _Member("INTU", "INTUIT INC", "US4612021034"),
    _Member("INVH", "INVITATION HOMES INC", "US46187W1071"),
    _Member("IP", "INTERNATIONAL PAPER CO", "US4601461035"),
    _Member("IQV", "IQVIA HOLDINGS INC", "US46266C1053"),
    _Member("IR", "INGERSOLL RAND INC", "US45687V1061"),
    _Member("IRM", "IRON MOUNTAIN INC", "US46284V1017"),
    _Member("ISRG", "INTUITIVE SURGICAL INC", "US46120E6023"),
    _Member("IT", "GARTNER INC", "US3666511072"),
    _Member("ITW", "ILLINOIS TOOL WORKS", "US4523081093"),
    _Member("IVZ", "INVESCO LTD", "USG491BT1085"),
    _Member("J", "JACOBS SOLUTIONS INC", "US46982L1089"),
    _Member("JBHT", "HUNT (JB) TRANSPRT SVCS INC", "US4456581077"),
    _Member("JBL", "JABIL INC", "US4663131039"),
    _Member("JCI", "JOHNSON CONTROLS INTERNATION", "USG515021057"),
    _Member("JKHY", "JACK HENRY + ASSOCIATES INC", "US4262811015"),
    _Member("JNJ", "JOHNSON + JOHNSON", "US4781601046"),
    _Member("JPM", "JPMORGAN CHASE + CO", "US46625H1005"),
    _Member("KDP", "KEURIG DR PEPPER INC", "US49271V1008"),
    _Member("KEY", "KEYCORP", "US4932671088"),
    _Member("KEYS", "KEYSIGHT TECHNOLOGIES IN", "US49338L1035"),
    _Member("KHC", "KRAFT HEINZ CO/THE", "US5007541064"),
    _Member("KIM", "KIMCO REALTY CORP", "US49446R1095"),
    _Member("KKR", "KKR + CO INC", "US48251W1045"),
    _Member("KLAC", "KLA CORP", "US4824801009"),
    _Member("KMB", "KIMBERLY CLARK CORP", "US4943681035"),
    _Member("KMI", "KINDER MORGAN INC", "US49456B1017"),
    _Member("KO", "COCA COLA CO/THE", "US1912161007"),
    _Member("KR", "KROGER CO", "US5010441013"),
    _Member("KVUE", "KENVUE INC", "US49177J1025"),
    _Member("L", "LOEWS CORP", "US5404241086"),
    _Member("LDOS", "LEIDOS HOLDINGS INC", "US5253271028"),
    _Member("LEN", "LENNAR CORP W/D", "US5260571048"),
    _Member("LH", "LABCORP HOLDINGS INC", "US5049221055"),
    _Member("LHX", "L3HARRIS TECHNOLOGIES INC", "US5024311095"),
    _Member("LII", "LENNOX INTERNATIONAL INC", "US5261071071"),
    _Member("LIN", "LINDE PLC", "USG549501033"),
    _Member("LITE", "LUMENTUM HOLDINGS INC", "US55024U1097"),
    _Member("LLY", "ELI LILLY + CO", "US5324571083"),
    _Member("LMT", "LOCKHEED MARTIN CORP", "US5398301094"),
    _Member("LNT", "ALLIANT ENERGY CORP", "US0188021085"),
    _Member("LOW", "LOWE S COS INC", "US5486611073"),
    _Member("LRCX", "LAM RESEARCH CORP", "US5128073062"),
    _Member("LULU", "LULULEMON ATHLETICA INC", "US5500211090"),
    _Member("LUV", "SOUTHWEST AIRLINES CO", "US8447411088"),
    _Member("LVS", "LAS VEGAS SANDS CORP", "US5178341070"),
    _Member("LYB", "LYONDELLBASELL INDU CL A", "USN537451007"),
    _Member("LYV", "LIVE NATION ENTERTAINMENT IN", "US5380341090"),
    _Member("MA", "MASTERCARD INC   A", "US57636Q1040"),
    _Member("MAA", "MID AMERICA APARTMENT COMM", "US59522J1034"),
    _Member("MAR", "MARRIOTT INTERNATIONAL  CL A", "US5719032022"),
    _Member("MAS", "MASCO CORP", "US5745991068"),
    _Member("MCD", "MCDONALD S CORP", "US5801351017"),
    _Member("MCHP", "MICROCHIP TECHNOLOGY INC", "US5950171042"),
    _Member("MCK", "MCKESSON CORP", "US58155Q1031"),
    _Member("MCO", "MOODY S CORP", "US6153691059"),
    _Member("MDLZ", "MONDELEZ INTERNATIONAL INC A", "US6092071058"),
    _Member("MDT", "MEDTRONIC PLC", "USG5960L1038"),
    _Member("MET", "METLIFE INC", "US59156R1086"),
    _Member("META", "META PLATFORMS INC CLASS A", "US30303M1027"),
    _Member("MGM", "MGM RESORTS INTERNATIONAL", "US5529531015"),
    _Member("MKC", "MCCORMICK + CO NON VTG SHRS", "US5797802064"),
    _Member("MLM", "MARTIN MARIETTA MATERIALS", "US5732841060"),
    _Member("MMM", "3M CO", "US88579Y1010"),
    _Member("MNST", "MONSTER BEVERAGE CORP", "US61174X1090"),
    _Member("MO", "ALTRIA GROUP INC", "US02209S1033"),
    _Member("MOS", "MOSAIC CO/THE", "US61945C1036"),
    _Member("MPC", "MARATHON PETROLEUM CORP", "US56585A1025"),
    _Member("MPWR", "MONOLITHIC POWER SYSTEMS INC", "US6098391054"),
    _Member("MRK", "MERCK + CO. INC.", "US58933Y1055"),
    _Member("MRNA", "MODERNA INC", "US60770K1079"),
    _Member("MRSH", "MARSH + MCLENNAN COS", "US5717481023"),
    _Member("MS", "MORGAN STANLEY", "US6174464486"),
    _Member("MSCI", "MSCI INC", "US55354G1004"),
    _Member("MSFT", "MICROSOFT CORP", "US5949181045"),
    _Member("MSI", "MOTOROLA SOLUTIONS INC", "US6200763075"),
    _Member("MTB", "M + T BANK CORP", "US55261F1049"),
    _Member("MTD", "METTLER TOLEDO INTERNATIONAL", "US5926881054"),
    _Member("MU", "MICRON TECHNOLOGY INC", "US5951121038"),
    _Member("NCLH", "NORWEGIAN CRUISE LINE HOLDIN", "USG667211043"),
    _Member("NDAQ", "NASDAQ INC", "US6311031081"),
    _Member("NDSN", "NORDSON CORP", "US6556631025"),
    _Member("NEE", "NEXTERA ENERGY INC", "US65339F1012"),
    _Member("NEM", "NEWMONT CORP", "US6516391066"),
    _Member("NFLX", "NETFLIX INC", "US64110L1061"),
    _Member("NI", "NISOURCE INC", "US65473P1057"),
    _Member("NKE", "NIKE INC  CL B", "US6541061031"),
    _Member("NOC", "NORTHROP GRUMMAN CORP", "US6668071029"),
    _Member("NOW", "SERVICENOW INC", "US81762P1021"),
    _Member("NRG", "NRG ENERGY INC", "US6293775085"),
    _Member("NSC", "NORFOLK SOUTHERN CORP", "US6558441084"),
    _Member("NTAP", "NETAPP INC", "US64110D1046"),
    _Member("NTRS", "NORTHERN TRUST CORP", "US6658591044"),
    _Member("NUE", "NUCOR CORP", "US6703461052"),
    _Member("NVDA", "NVIDIA CORP", "US67066G1040"),
    _Member("NVR", "NVR INC", "US62944T1051"),
    _Member("NWS", "NEWS CORP   CLASS B", "US65249B2088"),
    _Member("NWSA", "NEWS CORP   CLASS A", "US65249B1098"),
    _Member("NXPI", "NXP SEMICONDUCTORS NV", "USN6596X1092"),
    _Member("O", "REALTY INCOME CORP", "US7561091049"),
    _Member("ODFL", "OLD DOMINION FREIGHT LINE", "US6795801009"),
    _Member("OKE", "ONEOK INC", "US6826801036"),
    _Member("OMC", "OMNICOM GROUP", "US6819191064"),
    _Member("ON", "ON SEMICONDUCTOR", "US6821891057"),
    _Member("ORCL", "ORACLE CORP", "US68389X1054"),
    _Member("ORLY", "O REILLY AUTOMOTIVE INC", "US67103H1077"),
    _Member("OTIS", "OTIS WORLDWIDE CORP", "US68902V1070"),
    _Member("OXY", "OCCIDENTAL PETROLEUM CORP", "US6745991058"),
    _Member("PANW", "PALO ALTO NETWORKS INC", "US6974351057"),
    _Member("PAYX", "PAYCHEX INC", "US7043261079"),
    _Member("PCAR", "PACCAR INC", "US6937181088"),
    _Member("PCG", "P G + E CORP", "US69331C1080"),
    _Member("PEG", "PUBLIC SERVICE ENTERPRISE GP", "US7445731067"),
    _Member("PEP", "PEPSICO INC", "US7134481081"),
    _Member("PFE", "PFIZER INC", "US7170811035"),
    _Member("PFG", "PRINCIPAL FINANCIAL GROUP", "US74251V1026"),
    _Member("PG", "PROCTER + GAMBLE CO/THE", "US7427181091"),
    _Member("PGR", "PROGRESSIVE CORP", "US7433151039"),
    _Member("PH", "PARKER HANNIFIN CORP", "US7010941042"),
    _Member("PHM", "PULTEGROUP INC", "US7458671010"),
    _Member("PKG", "PACKAGING CORP OF AMERICA", "US6951561090"),
    _Member("PLD", "PROLOGIS INC", "US74340W1036"),
    _Member("PLTR", "PALANTIR TECHNOLOGIES INC A", "US69608A1088"),
    _Member("PM", "PHILIP MORRIS INTERNATIONAL", "US7181721090"),
    _Member("PNC", "PNC FINANCIAL SERVICES GROUP", "US6934751057"),
    _Member("PNR", "PENTAIR PLC", "USG7S00T1042"),
    _Member("PNW", "PINNACLE WEST CAPITAL", "US7234841010"),
    _Member("PODD", "INSULET CORP", "US45784P1012"),
    _Member("POOL", "POOL CORP", "US73278L1052"),
    _Member("PPG", "PPG INDUSTRIES INC", "US6935061076"),
    _Member("PPL", "PPL CORP", "US69351T1060"),
    _Member("PRU", "PRUDENTIAL FINANCIAL INC", "US7443201022"),
    _Member("PSA", "PUBLIC STORAGE", "US74460D1090"),
    _Member("PSKY", "PARAMOUNT SKYDANCE CL B", "US69932A2042"),
    _Member("PSX", "PHILLIPS 66", "US7185461040"),
    _Member("PTC", "PTC INC", "US69370C1009"),
    _Member("PWR", "QUANTA SERVICES INC", "US74762E1029"),
    _Member("PYPL", "PAYPAL HOLDINGS INC", "US70450Y1038"),
    _Member("Q", "QNITY ELECTRONICS INC", "US74743L1008"),
    _Member("QCOM", "QUALCOMM INC", "US7475251036"),
    _Member("RCL", "ROYAL CARIBBEAN CRUISES LTD", "USV7780T1035"),
    _Member("REG", "REGENCY CENTERS CORP", "US7588491032"),
    _Member("REGN", "REGENERON PHARMACEUTICALS", "US75886F1075"),
    _Member("RF", "REGIONS FINANCIAL CORP", "US7591EP1005"),
    _Member("RJF", "RAYMOND JAMES FINANCIAL INC", "US7547301090"),
    _Member("RL", "RALPH LAUREN CORP", "US7512121010"),
    _Member("RMD", "RESMED INC", "US7611521078"),
    _Member("ROK", "ROCKWELL AUTOMATION INC", "US7739031091"),
    _Member("ROL", "ROLLINS INC", "US7757111049"),
    _Member("ROP", "ROPER TECHNOLOGIES INC", "US7766961061"),
    _Member("ROST", "ROSS STORES INC", "US7782961038"),
    _Member("RSG", "REPUBLIC SERVICES INC", "US7607591002"),
    _Member("RTX", "RTX CORP", "US75513E1010"),
    _Member("RVTY", "REVVITY INC", "US7140461093"),
    _Member("SATS", "ECHOSTAR CORP A", "US2787681061"),
    _Member("SBAC", "SBA COMMUNICATIONS CORP", "US78410G1040"),
    _Member("SBUX", "STARBUCKS CORP", "US8552441094"),
    _Member("SCHW", "SCHWAB (CHARLES) CORP", "US8085131055"),
    _Member("SHW", "SHERWIN WILLIAMS CO/THE", "US8243481061"),
    _Member("SJM", "JM SMUCKER CO/THE", "US8326964058"),
    _Member("SLB", "SLB LTD", "US8068571087"),
    _Member("SMCI", "SUPER MICRO COMPUTER INC", "US86800U3023"),
    _Member("SNA", "SNAP ON INC", "US8330341012"),
    _Member("SNDK", "SANDISK CORP", "US80004C2008"),
    _Member("SNPS", "SYNOPSYS INC", "US8716071076"),
    _Member("SO", "SOUTHERN CO/THE", "US8425871071"),
    _Member("SOLV", "SOLVENTUM CORP", "US83444M1018"),
    _Member("SPG", "SIMON PROPERTY GROUP INC", "US8288061091"),
    _Member("SPGI", "S+P GLOBAL INC", "US78409V1044"),
    _Member("SRE", "SEMPRA", "US8168511090"),
    _Member("STE", "STERIS PLC", "USG8473T1000"),
    _Member("STLD", "STEEL DYNAMICS INC", "US8581191009"),
    _Member("STT", "STATE STREET CORP", "US8574771031"),
    _Member("STX", "SEAGATE TECHNOLOGY HOLDINGS", "USG7997R1035"),
    _Member("STZ", "CONSTELLATION BRANDS INC A", "US21036P1084"),
    _Member("SW", "SMURFIT WESTROCK PLC", "USG8267P1087"),
    _Member("SWK", "STANLEY BLACK + DECKER INC", "US8545021011"),
    _Member("SWKS", "SKYWORKS SOLUTIONS INC", "US83088M1027"),
    _Member("SYF", "SYNCHRONY FINANCIAL", "US87165B1035"),
    _Member("SYK", "STRYKER CORP", "US8636671013"),
    _Member("SYY", "SYSCO CORP", "US8718291078"),
    _Member("T", "AT+T INC", "US00206R1023"),
    _Member("TAP", "MOLSON COORS BEVERAGE CO   B", "US60871R2094"),
    _Member("TDG", "TRANSDIGM GROUP INC", "US8936411003"),
    _Member("TDY", "TELEDYNE TECHNOLOGIES INC", "US8793601050"),
    _Member("TECH", "BIO TECHNE CORP", "US09073M1045"),
    _Member("TEL", "TE CONNECTIVITY PLC", "USG870521097"),
    _Member("TER", "TERADYNE INC", "US8807701029"),
    _Member("TFC", "TRUIST FINANCIAL CORP", "US89832Q1094"),
    _Member("TGT", "TARGET CORP", "US87612E1064"),
    _Member("TJX", "TJX COMPANIES INC", "US8725401090"),
    _Member("TKO", "TKO GROUP HOLDINGS INC", "US87256C1018"),
    _Member("TMO", "THERMO FISHER SCIENTIFIC INC", "US8835561023"),
    _Member("TMUS", "T MOBILE US INC", "US8725901040"),
    _Member("TPL", "TEXAS PACIFIC LAND CORP", "US88262P1021"),
    _Member("TPR", "TAPESTRY INC", "US8760301072"),
    _Member("TRGP", "TARGA RESOURCES CORP", "US87612G1013"),
    _Member("TRMB", "TRIMBLE INC", "US8962391004"),
    _Member("TROW", "T ROWE PRICE GROUP INC", "US74144T1088"),
    _Member("TRV", "TRAVELERS COS INC/THE", "US89417E1091"),
    _Member("TSCO", "TRACTOR SUPPLY COMPANY", "US8923561067"),
    _Member("TSLA", "TESLA INC", "US88160R1014"),
    _Member("TSN", "TYSON FOODS INC CL A", "US9024941034"),
    _Member("TT", "TRANE TECHNOLOGIES PLC", "USG8994E1031"),
    _Member("TTD", "TRADE DESK INC/THE  CLASS A", "US88339J1051"),
    _Member("TTWO", "TAKE TWO INTERACTIVE SOFTWRE", "US8740541094"),
    _Member("TXN", "TEXAS INSTRUMENTS INC", "US8825081040"),
    _Member("TXT", "TEXTRON INC", "US8832031012"),
    _Member("TYL", "TYLER TECHNOLOGIES INC", "US9022521051"),
    _Member("UAL", "UNITED AIRLINES HOLDINGS INC", "US9100471096"),
    _Member("UBER", "UBER TECHNOLOGIES INC", "US90353T1007"),
    _Member("UDR", "UDR INC", "US9026531049"),
    _Member("UHS", "UNIVERSAL HEALTH SERVICES B", "US9139031002"),
    _Member("ULTA", "ULTA BEAUTY INC", "US90384S3031"),
    _Member("UNH", "UNITEDHEALTH GROUP INC", "US91324P1021"),
    _Member("UNP", "UNION PACIFIC CORP", "US9078181081"),
    _Member("UPS", "UNITED PARCEL SERVICE CL B", "US9113121068"),
    _Member("URI", "UNITED RENTALS INC", "US9113631090"),
    _Member("USB", "US BANCORP", "US9029733048"),
    _Member("V", "VISA INC CLASS A SHARES", "US92826C8394"),
    _Member("VEEV", "VEEVA SYSTEMS INC CLASS A", "US9224751084"),
    _Member("VICI", "VICI PROPERTIES INC", "US9256521090"),
    _Member("VLO", "VALERO ENERGY CORP", "US91913Y1001"),
    _Member("VLTO", "VERALTO CORP", "US92338C1036"),
    _Member("VMC", "VULCAN MATERIALS CO", "US9291601097"),
    _Member("VRSK", "VERISK ANALYTICS INC", "US92345Y1064"),
    _Member("VRSN", "VERISIGN INC", "US92343E1029"),
    _Member("VRT", "VERTIV HOLDINGS CO A", "US92537N1081"),
    _Member("VRTX", "VERTEX PHARMACEUTICALS INC", "US92532F1003"),
    _Member("VST", "VISTRA CORP", "US92840M1027"),
    _Member("VTR", "VENTAS INC", "US92276F1003"),
    _Member("VTRS", "VIATRIS INC", "US92556V1061"),
    _Member("VZ", "VERIZON COMMUNICATIONS INC", "US92343V1044"),
    _Member("WAB", "WABTEC CORP", "US9297401088"),
    _Member("WAT", "WATERS CORP", "US9418481035"),
    _Member("WBD", "WARNER BROS DISCOVERY INC", "US9344231041"),
    _Member("WDAY", "WORKDAY INC CLASS A", "US98138H1014"),
    _Member("WDC", "WESTERN DIGITAL CORP", "US9581021055"),
    _Member("WEC", "WEC ENERGY GROUP INC", "US92939U1060"),
    _Member("WELL", "WELLTOWER INC", "US95040Q1040"),
    _Member("WFC", "WELLS FARGO + CO", "US9497461015"),
    _Member("WM", "WASTE MANAGEMENT INC", "US94106L1098"),
    _Member("WMB", "WILLIAMS COS INC", "US9694571004"),
    _Member("WMT", "WALMART INC", "US9311421039"),
    _Member("WRB", "WR BERKLEY CORP", "US0844231029"),
    _Member("WSM", "WILLIAMS SONOMA INC", "US9699041011"),
    _Member("WST", "WEST PHARMACEUTICAL SERVICES", "US9553061055"),
    _Member("WTW", "WILLIS TOWERS WATSON PLC", "USG966291035"),
    _Member("WY", "WEYERHAEUSER CO", "US9621661043"),
    _Member("WYNN", "WYNN RESORTS LTD", "US9831341071"),
    _Member("XEL", "XCEL ENERGY INC", "US98389B1008"),
    _Member("XOM", "EXXON MOBIL CORP", "US30231G1022"),
    _Member("XYL", "XYLEM INC", "US98419M1009"),
    _Member("XYZ", "BLOCK INC", "US8522341036"),
    _Member("YUM", "YUM  BRANDS INC", "US9884981013"),
    _Member("ZBH", "ZIMMER BIOMET HOLDINGS INC", "US98956P1021"),
    _Member("ZBRA", "ZEBRA TECHNOLOGIES CORP CL A", "US9892071054"),
    _Member("ZTS", "ZOETIS INC", "US98978V1035"),
)
# ---------------------------------------------------------------------------
# END GENERATED
# ---------------------------------------------------------------------------

assert len(SP500_MEMBERS) >= 500, (
    f"SP500_MEMBERS has {len(SP500_MEMBERS)} entries, expected ~503"
)

# Convenience dict for external access and test assertions.
SP500_ISINS: dict[str, str] = {m.ticker: m.isin for m in SP500_MEMBERS}


def _epoch_to_date(value: Any) -> date | None:
    if value is None:
        return None
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=UTC).date()
    except (OverflowError, OSError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # noqa: PLR0124 — NaN check
        return None
    return out


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def _parse_yield(value: Any) -> float | None:
    """Convert yfinance ``trailingAnnualDividendYield`` (decimal, e.g.
    0.0194 = 1.94%) into the percent-units expected by ``Constituent``.
    Returns None for missing/zero so downstream "with dividend" counts
    only see real distributions.
    """
    parsed = _coerce_float(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed * 100


def _resolve_isin_from_yfinance(info: dict[str, Any]) -> str | None:
    """yfinance occasionally has an 'isin' key. Treat '-' as missing."""
    raw = info.get("isin")
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    if not raw or raw == "-":
        return None
    return raw


async def _fetch_yf_info(ticker: str) -> dict[str, Any]:
    """Fetch yfinance.Ticker(ticker).info off the event loop."""

    def _call() -> dict[str, Any]:
        import yfinance as yf  # pyright: ignore[reportMissingTypeStubs]

        try:
            data: Any = yf.Ticker(ticker).info  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        except Exception as exc:
            logger.warning("yfinance .info failed for %s: %s", ticker, exc)
            return {}
        if isinstance(data, dict):
            return cast(dict[str, Any], data)
        return {}

    return await asyncio.to_thread(_call)


def _build_constituent(member: _Member, yf_info: dict[str, Any]) -> Constituent:
    """Merge yfinance + static map into a Constituent. Static ISIN is the
    fallback; yfinance ISIN takes precedence on the rare chance it appears.
    """
    isin: str | None = _resolve_isin_from_yfinance(yf_info)
    source: str | None = "yfinance" if isin else None
    if not isin:
        isin = member.isin
        source = "static"

    name = (
        _coerce_str(yf_info.get("shortName"))
        or _coerce_str(yf_info.get("longName"))
        or member.name
    )

    price = _coerce_float(yf_info.get("currentPrice"))
    if price is None:
        price = _coerce_float(yf_info.get("regularMarketPrice"))

    return Constituent(
        ticker=member.ticker,
        name=name,
        isin=isin,
        isin_source=source,
        country=INDEX_COUNTRY,
        price=price,
        currency=_coerce_str(yf_info.get("currency")),
        ex_div_date=_epoch_to_date(yf_info.get("exDividendDate")),
        ttm_div_yield=_parse_yield(yf_info.get("trailingAnnualDividendYield")),
        beta=_coerce_float(yf_info.get("beta")),
        market_cap=_coerce_float(yf_info.get("marketCap")),
        sector=_coerce_str(yf_info.get("sector")),
        weight=member.weight,
    )


async def _fetch_member(member: _Member) -> Constituent:
    """Fetch yfinance for one member; never raises.

    On total upstream failure we still emit a Constituent populated from
    the static map (ticker/name/ISIN), so the index always returns a
    complete constituent list and ISIN coverage stays at 100%.
    """
    try:
        info = await _fetch_yf_info(member.ticker)
    except Exception as exc:
        logger.warning("S&P 500: yfinance hard-failed for %s: %s", member.ticker, exc)
        info = {}
    try:
        return _build_constituent(member, info)
    except Exception as exc:
        logger.warning(
            "S&P 500: falling back to static-only constituent for %s: %s",
            member.ticker,
            exc,
        )
        return Constituent(
            ticker=member.ticker,
            name=member.name,
            isin=member.isin,
            isin_source="static",
            country=INDEX_COUNTRY,
            currency="USD",
            weight=member.weight,
        )


class SP500Adapter(IndexAdapter):
    """Adapter for the S&P 500 index."""

    name: str = INDEX_NAME
    country: str = INDEX_COUNTRY
    source: str = SOURCE_LABEL

    def __init__(self, members: tuple[_Member, ...] = SP500_MEMBERS) -> None:
        self._members = members

    async def fetch_constituents(self) -> Index:
        constituents = await asyncio.gather(
            *(_fetch_member(m) for m in self._members)
        )
        return Index(
            name=self.name,
            country=self.country,
            constituents=list(constituents),
            fetched_at=datetime.now(tz=UTC),
            source=self.source,
        )
