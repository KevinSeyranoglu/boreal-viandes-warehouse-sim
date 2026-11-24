/* Dock-to-stock time: minutes from the receiving scan to the put-away scan, per licence plate.
   A key receiving KPI: the longer a pallet waits on the dock, the bigger the cold-chain risk. */
proc sql;
  create table work.d2s as
  select r.THLPN, r.THITEM, i.IMZONE,
         dhms(r.THDATE, 0, 0, r.THTIME)              as rcv_dt format=datetime19.,
         dhms(p.THDATE, 0, 0, p.THTIME)              as put_dt format=datetime19.,
         (calculated put_dt - calculated rcv_dt) / 60 as d2s_min format=8.1,
         hour(r.THTIME)                               as rcv_hour
  from wms.ithtrn(where=(THTYPE in ('RCV','RQA'))) as r
       inner join wms.ithtrn(where=(THTYPE = 'PUT')) as p on p.THLPN = r.THLPN
       inner join wms.itmmst as i on i.IMITEM = r.THITEM;
quit;

title "Dock-to-stock (minutes) by storage room";
proc means data=work.d2s n mean median p90 max maxdec=1;
  class IMZONE;
  var d2s_min;
run;

title "Dock-to-stock by hour of receipt (the morning rush)";
proc means data=work.d2s n mean p90 maxdec=1 nonobs;
  class rcv_hour;
  var d2s_min;
run;

title "Distribution of dock-to-stock time";
proc sgplot data=work.d2s;
  histogram d2s_min / binwidth=5;
  xaxis label="minutes from receiving scan to put-away" max=240;
run;
title;
