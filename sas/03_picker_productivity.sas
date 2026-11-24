/* Picker productivity from pick scans (THTYPE = 'PCK'): cases, lines and cases per scanning hour
   per employee and day. The scanning span (first to last pick) approximates time on picking. */
proc sql;
  create table work.pick_day as
  select THUSER, THDATE format=yymmdd10.,
         count(*)                as lines,
         sum(THQTY)              as cases,
         sum(THWGT)              as kg format=comma12.1,
         (max(THTIME) - min(THTIME)) / 3600 as scan_hours format=6.2
  from wms.ithtrn
  where THTYPE = 'PCK'
  group by THUSER, THDATE
  having calculated scan_hours > 1;
quit;

data work.pick_day;
  set work.pick_day;
  cases_per_hour = cases / scan_hours;
  lines_per_hour = lines / scan_hours;
  format cases_per_hour lines_per_hour 6.1;
run;

title "Picker productivity (per employee, averaged over days)";
proc means data=work.pick_day nway n mean median maxdec=1;
  class THUSER;
  var cases_per_hour lines_per_hour;
  output out=work.pick_emp(drop=_type_ _freq_) mean(cases_per_hour)=cph;
run;

proc rank data=work.pick_emp out=work.pick_emp groups=4;
  var cph;
  ranks quartile;
run;

title "Pickers by productivity quartile (0 = lowest)";
proc freq data=work.pick_emp;
  tables quartile;
run;

title "Cases per scanning hour: one box per picker";
proc sgplot data=work.pick_day;
  vbox cases_per_hour / category=THUSER;
  xaxis display=(nolabel) fitpolicy=thin;
run;
title;
