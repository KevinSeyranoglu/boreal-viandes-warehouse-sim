/*--------------------------------------------------------------------------------------------
  Boréal Viandes – SAS analysis of the AS/400 WMS extract.
  Run in order: 00_setup, 01_import_as400, then any analysis program.
  The extract comes from:  python analytics/export_as400.py   (-> data/as400/*.TXT)
--------------------------------------------------------------------------------------------*/
%let root  = /path/to/boreal-viandes-warehouse-sim;      /* <-- change to your clone */
%let as400 = &root/data/as400;

options dlcreatedir nofmterr validvarname=upcase;
libname wms "&root/sas/lib";                              /* SAS datasets created by 01_import */

/* transaction types (ITHTRN.THTYPE) and their SAP-equivalent movement types */
proc format;
  value $txn
    'RCV' = 'Received (101)'          'RQA' = 'Received to QA (101 QI)'
    'REJ' = 'Refused at door (122)'   'TXI' = 'Taxi dock -> drop point'
    'PUT' = 'Put-away to rack'        'QAM' = 'Moved to QA cage'
    'QRL' = 'QA release (321)'        'QRJ' = 'QA reject, scrap (553)'
    'RTV' = 'Return to vendor (122)'  'PCK' = 'Picked (cases to outbound pallet)'
    'BLD' = 'Outbound pallet built'   'LOD' = 'Loaded on trailer'
    'SHP' = 'Goods issue (601)'       'SPL' = 'Expired, written off (551)'
    'ADJ' = 'Damage adjustment (551)' 'RCL' = 'Recall removal (344)'
    'DSP' = 'Disposed';
run;
