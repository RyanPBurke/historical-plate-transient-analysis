-- v095a Stage A SQL templates RC3
-- PostgreSQL through APPLAUSE TAP.
-- Only the named row placeholder in one extracted query family may be replaced at runtime.
-- Runtime rows are deterministic SELECT/UNION ALL relations containing canonical base-10 integers from frozen parent metadata.

-- BEGIN Q0_SELECTED_SOLUTION_BINDING
SELECT
    w.key_id,
    w.solution_id,
    w.expected_plate_id,
    w.expected_scan_id,
    s.plate_id AS returned_plate_id,
    s.scan_id AS returned_scan_id,
    s.process_id,
    s.solution_num,
    s.solutionset_id,
    CASE WHEN s.solution_id IS NULL THEN 0 ELSE 1 END AS solution_row_found
FROM (
    /*__Q0_VALUES__*/
) AS w
LEFT JOIN applause_dr4.solution AS s
  ON s.solution_id = w.solution_id
ORDER BY w.key_id;
-- END Q0_SELECTED_SOLUTION_BINDING

-- BEGIN Q1_SELECTED_SCIENCE_KEY_AGGREGATES
SELECT
    s.key_id,
    s.plate_id,
    s.scan_id,
    s.process_id,
    s.solution_num,
    COUNT(sc.plate_id) AS source_rows,

    SUM(CASE WHEN sc.gaiaedr3_id IS NULL AND sc.plate_id IS NOT NULL THEN 1 ELSE 0 END) AS gaia_null,
    SUM(CASE WHEN sc.gaiaedr3_id < 0 THEN 1 ELSE 0 END) AS gaia_lt0,
    SUM(CASE WHEN sc.gaiaedr3_id = 0 THEN 1 ELSE 0 END) AS gaia_eq0,
    SUM(CASE WHEN sc.gaiaedr3_id > 0 THEN 1 ELSE 0 END) AS gaia_gt0,

    SUM(CASE WHEN sc.sextractor_flags IS NULL AND sc.plate_id IS NOT NULL THEN 1 ELSE 0 END) AS sexflag_null,
    SUM(CASE WHEN sc.sextractor_flags < 0 THEN 1 ELSE 0 END) AS sexflag_lt0,
    SUM(CASE WHEN sc.sextractor_flags = 0 THEN 1 ELSE 0 END) AS sexflag_eq0,
    SUM(CASE WHEN sc.sextractor_flags > 0 THEN 1 ELSE 0 END) AS sexflag_gt0,

    SUM(CASE WHEN sc.model_prediction IS NULL AND sc.plate_id IS NOT NULL THEN 1 ELSE 0 END) AS mp_null,
    SUM(CASE WHEN sc.model_prediction < 0 THEN 1 ELSE 0 END) AS mp_lt0,
    SUM(CASE WHEN sc.model_prediction >= 0 AND sc.model_prediction < 0.10 THEN 1 ELSE 0 END) AS mp_0_010,
    SUM(CASE WHEN sc.model_prediction >= 0.10 AND sc.model_prediction < 0.50 THEN 1 ELSE 0 END) AS mp_010_050,
    SUM(CASE WHEN sc.model_prediction >= 0.50 AND sc.model_prediction < 0.90 THEN 1 ELSE 0 END) AS mp_050_090,
    SUM(CASE WHEN sc.model_prediction >= 0.90 AND sc.model_prediction < 0.99 THEN 1 ELSE 0 END) AS mp_090_099,
    SUM(CASE WHEN sc.model_prediction >= 0.99 AND sc.model_prediction <= 1.00 THEN 1 ELSE 0 END) AS mp_099_100,
    SUM(CASE WHEN sc.model_prediction > 1.00 THEN 1 ELSE 0 END) AS mp_gt1,

    SUM(CASE WHEN sc.ra_error IS NULL AND sc.plate_id IS NOT NULL THEN 1 ELSE 0 END) AS raerr_null,
    SUM(CASE WHEN sc.ra_error < 0 THEN 1 ELSE 0 END) AS raerr_lt0,
    SUM(CASE WHEN sc.ra_error = 0 THEN 1 ELSE 0 END) AS raerr_eq0,
    SUM(CASE WHEN sc.ra_error > 0 AND sc.ra_error <= 0.25 THEN 1 ELSE 0 END) AS raerr_0_025,
    SUM(CASE WHEN sc.ra_error > 0.25 AND sc.ra_error <= 0.50 THEN 1 ELSE 0 END) AS raerr_025_050,
    SUM(CASE WHEN sc.ra_error > 0.50 AND sc.ra_error <= 1.00 THEN 1 ELSE 0 END) AS raerr_050_100,
    SUM(CASE WHEN sc.ra_error > 1.00 AND sc.ra_error <= 2.00 THEN 1 ELSE 0 END) AS raerr_100_200,
    SUM(CASE WHEN sc.ra_error > 2.00 AND sc.ra_error <= 5.00 THEN 1 ELSE 0 END) AS raerr_200_500,
    SUM(CASE WHEN sc.ra_error > 5.00 AND sc.ra_error <= 10.00 THEN 1 ELSE 0 END) AS raerr_500_1000,
    SUM(CASE WHEN sc.ra_error > 10.00 THEN 1 ELSE 0 END) AS raerr_gt1000,

    SUM(CASE WHEN sc.dec_error IS NULL AND sc.plate_id IS NOT NULL THEN 1 ELSE 0 END) AS decerr_null,
    SUM(CASE WHEN sc.dec_error < 0 THEN 1 ELSE 0 END) AS decerr_lt0,
    SUM(CASE WHEN sc.dec_error = 0 THEN 1 ELSE 0 END) AS decerr_eq0,
    SUM(CASE WHEN sc.dec_error > 0 AND sc.dec_error <= 0.25 THEN 1 ELSE 0 END) AS decerr_0_025,
    SUM(CASE WHEN sc.dec_error > 0.25 AND sc.dec_error <= 0.50 THEN 1 ELSE 0 END) AS decerr_025_050,
    SUM(CASE WHEN sc.dec_error > 0.50 AND sc.dec_error <= 1.00 THEN 1 ELSE 0 END) AS decerr_050_100,
    SUM(CASE WHEN sc.dec_error > 1.00 AND sc.dec_error <= 2.00 THEN 1 ELSE 0 END) AS decerr_100_200,
    SUM(CASE WHEN sc.dec_error > 2.00 AND sc.dec_error <= 5.00 THEN 1 ELSE 0 END) AS decerr_200_500,
    SUM(CASE WHEN sc.dec_error > 5.00 AND sc.dec_error <= 10.00 THEN 1 ELSE 0 END) AS decerr_500_1000,
    SUM(CASE WHEN sc.dec_error > 10.00 THEN 1 ELSE 0 END) AS decerr_gt1000,

    SUM(CASE WHEN sc.ra_icrs IS NULL AND sc.dec_icrs IS NULL AND sc.plate_id IS NOT NULL THEN 1 ELSE 0 END) AS coord_both_null,
    SUM(CASE WHEN sc.ra_icrs IS NULL AND sc.dec_icrs IS NOT NULL THEN 1 ELSE 0 END) AS coord_ra_null_only,
    SUM(CASE WHEN sc.ra_icrs IS NOT NULL AND sc.dec_icrs IS NULL THEN 1 ELSE 0 END) AS coord_dec_null_only,
    SUM(CASE WHEN sc.ra_icrs >= 0 AND sc.ra_icrs < 360 AND sc.dec_icrs >= -90 AND sc.dec_icrs <= 90 THEN 1 ELSE 0 END) AS coord_valid_icrs_bounds,
    SUM(CASE WHEN sc.ra_icrs IS NOT NULL AND sc.dec_icrs IS NOT NULL AND NOT (sc.ra_icrs >= 0 AND sc.ra_icrs < 360 AND sc.dec_icrs >= -90 AND sc.dec_icrs <= 90) THEN 1 ELSE 0 END) AS coord_out_of_bounds,

    SUM(CASE WHEN sc.annular_bin IS NULL AND sc.plate_id IS NOT NULL THEN 1 ELSE 0 END) AS annular_null,
    SUM(CASE WHEN sc.annular_bin = 1 THEN 1 ELSE 0 END) AS annular_1,
    SUM(CASE WHEN sc.annular_bin = 2 THEN 1 ELSE 0 END) AS annular_2,
    SUM(CASE WHEN sc.annular_bin = 3 THEN 1 ELSE 0 END) AS annular_3,
    SUM(CASE WHEN sc.annular_bin = 4 THEN 1 ELSE 0 END) AS annular_4,
    SUM(CASE WHEN sc.annular_bin = 5 THEN 1 ELSE 0 END) AS annular_5,
    SUM(CASE WHEN sc.annular_bin = 6 THEN 1 ELSE 0 END) AS annular_6,
    SUM(CASE WHEN sc.annular_bin = 7 THEN 1 ELSE 0 END) AS annular_7,
    SUM(CASE WHEN sc.annular_bin = 8 THEN 1 ELSE 0 END) AS annular_8,
    SUM(CASE WHEN sc.annular_bin = 9 THEN 1 ELSE 0 END) AS annular_9,
    SUM(CASE WHEN sc.annular_bin < 1 OR sc.annular_bin > 9 THEN 1 ELSE 0 END) AS annular_other
FROM (
    /*__Q1_VALUES__*/
) AS s
LEFT JOIN applause_dr4.source_calib AS sc
  ON sc.plate_id = s.plate_id
 AND sc.scan_id = s.scan_id
 AND sc.process_id = s.process_id
 AND sc.solution_num = s.solution_num
GROUP BY s.key_id, s.plate_id, s.scan_id, s.process_id, s.solution_num
ORDER BY s.key_id;
-- END Q1_SELECTED_SCIENCE_KEY_AGGREGATES

-- BEGIN Q2_PHYSICAL_PLATE_PROCESSING_MULTIPLICITY
SELECT
    p.plate_id,
    COUNT(sc.plate_id) AS all_processing_source_rows,
    COUNT(DISTINCT sc.scan_id) AS distinct_scans,
    COUNT(DISTINCT sc.process_id) AS distinct_processes,
    CASE
        WHEN COUNT(sc.plate_id) = 0 THEN 0
        ELSE COUNT(DISTINCT (sc.process_id, sc.solution_num))
    END AS distinct_process_solution_nums,
    CASE
        WHEN COUNT(sc.plate_id) = 0 THEN 0
        ELSE COUNT(DISTINCT (sc.scan_id, sc.process_id, sc.solution_num))
    END AS distinct_scan_process_solution_nums
FROM (
    /*__Q2_VALUES__*/
) AS p
LEFT JOIN applause_dr4.source_calib AS sc
  ON sc.plate_id = p.plate_id
GROUP BY p.plate_id
ORDER BY p.plate_id;
-- END Q2_PHYSICAL_PLATE_PROCESSING_MULTIPLICITY
