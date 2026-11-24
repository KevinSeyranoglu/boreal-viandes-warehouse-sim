/* Customer service: OTIF (on time and in full) by route and customer, and the fines it costs. */
data work.orders;
  set wms.ordhdr;
  in_full = (OHQSHP >= OHQORD * 0.999);
  otif    = (OHONTM = 'Y' and in_full);
  fill    = OHQSHP / OHQORD;
  ship_month = intnx('month', OHSDAT, 0);
  format ship_month yymmn6. fill percent8.2;
run;

proc sql;
  create table work.orders as
  select o.*, c.CMNAME, c.CMTYPE, c.CMCITY
  from work.orders o left join wms.cusmst c on c.CMCUST = o.OHCUST;
quit;

title "OTIF and fines by route and month";
proc tabulate data=work.orders format=8.3;
  class OHROUT ship_month;
  var otif fill OHFINE;
  table OHROUT all, ship_month all;
  table OHROUT all, (otif*mean*f=percent8.1 fill*mean*f=percent8.2 OHFINE*sum*f=dollar12.0);
run;

title "Ten customers with the lowest OTIF";
proc sql outobs=10;
  select OHCUST, CMNAME, CMTYPE, count(*) as orders, mean(otif) as otif format=percent8.1,
         sum(OHFINE) as fines format=dollar12.0
  from work.orders group by OHCUST, CMNAME, CMTYPE order by otif;
quit;
title;
