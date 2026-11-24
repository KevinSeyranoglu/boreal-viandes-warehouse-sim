/* Lot traceability for a recall: where the lot came from, every scan of it, the outbound pallets it
   was picked onto and the customers those pallets were shipped to (CFIA expects this in hours). */
%macro trace(lot=);
  title "Lot &lot – receipts (purchase order, supplier, pack and best-before dates)";
  proc sql;
    select d.PDPO, h.PHVEND, d.PDLPN, d.PDITEM, d.PDQTY, d.PDPKDT format=yymmdd10.,
           d.PDBBDT format=yymmdd10., d.PDTEMP, d.PDDEC
    from wms.podtl d inner join wms.pohdr h on h.PHPO = d.PDPO
    where strip(d.PDLOT) = "&lot";

  title "Lot &lot – every scan";
    select THDATE format=yymmdd10., THTIME format=time8., THTYPE format=$txn., THLPN, THQTY,
           THFLOC, THTLOC, THUSER, THDOC
    from wms.ithtrn
    where strip(THLOT) = "&lot"
    order by THDATE, THTIME;

  title "Lot &lot – customers reached (outbound pallets that carried it, and their goods issue)";
    create table work.trace_out as
    select distinct p.THLPN as out_lpn, sum(p.THQTY) as cases
    from wms.ithtrn p
    where p.THTYPE = 'PCK' and strip(p.THLOT) = "&lot"
    group by p.THLPN;

    select o.out_lpn, o.cases, s.THDATE format=yymmdd10., s.THTIME format=time8.,
           substr(s.THTLOC, 6) as customer, c.CMNAME, c.CMCITY, s.THDOC as bol
    from work.trace_out o
         left join wms.ithtrn(where=(THTYPE = 'SHP')) s on s.THLPN = o.out_lpn
         left join wms.cusmst c on c.CMCUST = substr(s.THTLOC, 6)
    order by customer;
  quit;
  title;
%mend trace;

/* example: lot 6370 (frozen ground pork C403), recalled on 2027-05-29 after reaching 33 stores (baseline run, seed 42) */
%trace(lot=6370);
