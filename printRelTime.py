from datetime import datetime, timezone

second =          1.0
minute = second *  60
hour   = minute *  60
day    = hour   *  24
month  = day    *  30
year   = day    * 365
week   = day    *   7

timeNamesDict: dict[str, tuple[str, tuple[tuple[str]]]] = {
	"pol": (
		" temu",
		(
			("sekund", "minut", "godzin", "dni", "miesięcy", "lat"),
			("sek"   , "min"  , "godz"  , "dni", "mies"    , "lat"),
			("s"     , "m"    , "g"     , "d"  , "M"       , "l"  ),
		)
	),
	"ang": (
		" ago",
		(
			("seconds", "minutes", "hours", "days", "months", "years"),
			("sec"    , "min"    , "hour" , "days", "mon"   , "year" ),
			("s"      , "m"      , "h"    , "d"   , "M"     , "y"    ),
		)
	),
}

def toFixed(num, dec = "0"):
	return format(num, "." + dec + "f")

def printRelTime(
	epoch_s   : float = 0    ,
	czyDiff   : bool  = True ,
	lang      : str   = "ang",
	compact   : int   = 0    ,
	space     : str   = " "  ,
	ago       : bool  = True ,
	leftAlign : bool  = False,
	prec      : str   = None ,
):
	czas = (datetime.now(timezone.utc).timestamp() - epoch_s) if czyDiff else epoch_s
	znak = "-" if czas < 0 else ""
	czas = abs(czas)
	prec0 = "0" if prec is None else prec
	prec1 = "1" if prec is None else prec

	try:
		agoStr, timeNamesArr = timeNamesDict[lang]
		timeNames = timeNamesArr[compact]
	except:
		raise Exception("Language not supported")

	if leftAlign:
		maxLen = max(timeNames, key=len)
		timeNames = tuple(map(lambda x: x.ljust(maxLen), timeNames))

	if   czas < minute: czytCzas =                                                              toFixed(czas / second, prec0)  + space + timeNames[0]
	elif czas < hour  : czytCzas = (toFixed(czas / minute, prec1) if czas <= minute * 9.95 else toFixed(czas / minute, prec0)) + space + timeNames[1]
	elif czas < day   : czytCzas = (toFixed(czas / hour  , prec1) if czas <= hour   * 9.95 else toFixed(czas / hour  , prec0)) + space + timeNames[2]
	elif czas < month : czytCzas = (toFixed(czas / day   , prec1) if czas <= day    * 9.95 else toFixed(czas / day   , prec0)) + space + timeNames[3]
	elif czas < year  : czytCzas = (toFixed(czas / month , prec1) if czas <= month  * 9.95 else toFixed(czas / month , prec0)) + space + timeNames[4]
	else					: czytCzas = (toFixed(czas / year  , prec1) if czas <= year   * 9.95 else toFixed(czas / year  , prec0)) + space + timeNames[5]

	return znak + czytCzas + (agoStr if ago else "")
