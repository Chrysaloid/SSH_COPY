from datetime import datetime as _datetime, timezone as _timezone

SECOND =          1.0
MINUTE = SECOND *  60
HOUR   = MINUTE *  60
DAY    = HOUR   *  24
MONTH  = DAY    *  30
YEAR   = DAY    * 365
WEEK   = DAY    *   7

_TIME_NAMES_DICT: dict[str, tuple[str, tuple[tuple[str]]]] = {
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

def to_fixed(num, dec = "0"):
	return format(num, f".{dec}f")

def get_rel_time(
	epoch_s    : float | _datetime = 0    ,
	czy_diff   : bool              = True ,
	lang       : str               = "ang",
	compact    : int               = 0    ,
	space      : str               = " "  ,
	ago        : bool              = True ,
	left_align : bool              = False,
	prec       : str               = None ,
):
	epoch_s = epoch_s.timestamp() if isinstance(epoch_s, _datetime) else epoch_s
	czas = (_datetime.now(_timezone.utc).timestamp() - epoch_s) if czy_diff else epoch_s
	znak = "-" if czas < 0 else ""
	czas = abs(czas)
	prec0 = "0" if prec is None else prec
	prec1 = "1" if prec is None else prec

	try:
		ago_str, time_names_arr = _TIME_NAMES_DICT[lang]
		time_names = time_names_arr[compact]
	except:
		raise Exception("Language not supported")

	if left_align:
		max_len = max(time_names, key=len)
		time_names = tuple(map(lambda x: x.ljust(max_len), time_names))

	if   czas < MINUTE: czyt_czas =                                                               to_fixed(czas / SECOND, prec0)  + space + time_names[0]
	elif czas < HOUR  : czyt_czas = (to_fixed(czas / MINUTE, prec1) if czas <= MINUTE * 9.95 else to_fixed(czas / MINUTE, prec0)) + space + time_names[1]
	elif czas < DAY   : czyt_czas = (to_fixed(czas / HOUR  , prec1) if czas <= HOUR   * 9.95 else to_fixed(czas / HOUR  , prec0)) + space + time_names[2]
	elif czas < MONTH : czyt_czas = (to_fixed(czas / DAY   , prec1) if czas <= DAY    * 9.95 else to_fixed(czas / DAY   , prec0)) + space + time_names[3]
	elif czas < YEAR  : czyt_czas = (to_fixed(czas / MONTH , prec1) if czas <= MONTH  * 9.95 else to_fixed(czas / MONTH , prec0)) + space + time_names[4]
	else					: czyt_czas = (to_fixed(czas / YEAR , prec1) if czas <= YEAR  * 9.95 else to_fixed(czas / YEAR , prec0)) + space + time_names[5]

	return znak + czyt_czas + (ago_str if ago else "")

if __name__ == "__main__": # Example usage
	from my_libs.print_rel_time import get_rel_time

	# from my_libs.print_rel_time import DAY, get_rel_time, HOUR, MINUTE, MONTH, SECOND, WEEK, YEAR

	print(get_rel_time())
	print(get_rel_time(1000000000))
