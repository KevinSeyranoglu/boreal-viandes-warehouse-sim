/* Supplier scorecard from purchase orders and receipts: punctuality, short shipments, temperature
   refusals, and shelf life left at receipt (the leading indicator of spoilage). */
proc sql;
  create table work.po as
  select PHPO, PHVEND,
         (dhms(PHADAT,0,0,PHATIM) - dhms(PHSDAT,0,0,PHSTIM)) / 60 as late_min,
         (dhms(PHDDAT,0,0,PHDTIM) - dhms(PHADAT,0,0,PHATIM)) / 60 as yard_wait_min,
         PHQORD, PHQRCV, PHQREJ, PHREEF
  from wms.pohdr;

  create table work.rcv as
  select h.PHVEND, d.PDITEM, d.PDBBDT - d.PDRDAT as days_left, d.PDDEC
  from wms.podtl d inner join wms.pohdr h on h.PHPO = d.PDPO;

  title "Supplier scorecard";
  select p.PHVEND, v.VMNAME,
         count(*)                                          as trucks,
         mean(p.late_min <= 15)                            as on_time_pct format=percent8.1,
         mean(p.late_min)                                  as avg_late_min format=6.0,
         1 - sum(p.PHQRCV) / sum(p.PHQORD)                 as short_ship_pct format=percent8.2,
         sum(p.PHQREJ) / sum(p.PHQRCV)                     as refused_pct format=percent8.2,
         sum(p.PHREEF = 'Y')                               as reefer_failures,
         mean(p.yard_wait_min)                             as avg_yard_wait format=6.0
  from work.po p inner join wms.vndmst v on v.VMVEND = p.PHVEND
  group by p.PHVEND, v.VMNAME
  order by on_time_pct;
quit;

title "Days of shelf life left at receipt, by supplier and item (short = spoilage risk)";
proc means data=work.rcv n mean p5 min maxdec=1;
  class PHVEND PDITEM;
  var days_left;
run;
title;
