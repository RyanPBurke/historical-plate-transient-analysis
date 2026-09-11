-- v095a Stage A SQL templates RC3
-- PostgreSQL through APPLAUSE TAP.
-- Only the named VALUES placeholder in one extracted query family may be replaced at runtime.
-- All inserted values are canonical base-10 integers generated from frozen parent metadata.

-- BEGIN Q0_SELECTED_SOLUTION_BINDING
WITH wanted(key_id, solution_id, expected_plate_id, expected_scan_id) AS (
    VALUES
    /*__Q0_VALUES__*/
)
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
FROM wanted AS w
LEFT JOIN applause_dr4.solution AS s
  ON s.solution_id = w.solution_id
ORDER BY w.key_id;
-- END Q0_SELECTED_SOLUTION_BINDING

-- BEGIN Q1_SELECTED_SCIENCE_KEY_AGGREGATES
WITH selected(key_id, plate_id, scan_id, process_id, solution_num) AS (
    VALUES
    /*__Q1_VALUES__*/
)
SELECT
    s.key_id,
    s.plate_id,
    s.scan_id,
    s.process_id,
    s.solution_num,
    COUNT(sc.plate_id) AS source_rows,

    COUNT(*) FILTER (WHERE sc.gaiaedr3_id IS NULL AND sc.plate_id IS NOT NULL) AS gaia_null,
    COUNT(*) FILTER (WHERE sc.gaiaedr3_id < 0) AS gaia_lt0,
    COUNT(*) FILTER (WHERE sc.gaiaedr3_id = 0) AS gaia_eq0,
    COUNT(*) FILTER (WHERE sc.gaiaedr3_id > 0) AS gaia_gt0,

    COUNT(*) FILTER (WHERE sc.sextractor_flags IS NULL AND sc.plate_id IS NOT NULL) AS sexflag_null,
    COUNT(*) FILTER (WHERE sc.sextractor_flags < 0) AS sexflag_lt0,
    COUNT(*) FILTER (WHERE sc.sextractor_flags = 0) AS sexflag_eq0,
    COUNT(*) FILTER (WHERE sc.sextractor_flags > 0) AS sexflag_gt0,

    COUNT(*) FILTER (WHERE sc.model_prediction IS NULL AND sc.plate_id IS NOT NULL) AS mp_null,
    COUNT(*) FILTER (WHERE sc.model_prediction < 0) AS mp_lt0,
    COUNT(*) FILTER (WHERE sc.model_prediction >= 0 AND sc.model_prediction < 0.10) AS mp_0_010,
    COUNT(*) FILTER (WHERE sc.model_prediction >= 0.10 AND sc.model_prediction < 0.50) AS mp_010_050,
    COUNT(*) FILTER (WHERE sc.model_prediction >= 0.50 AND sc.model_prediction < 0.90) AS mp_050_090,
    COUNT(*) FILTER (WHERE sc.model_prediction >= 0.90 AND sc.model_prediction < 0.99) AS mp_090_099,
    COUNT(*) FILTER (WHERE sc.model_prediction >= 0.99 AND sc.model_prediction <= 1.00) AS mp_099_100,
    COUNT(*) FILTER (WHERE sc.model_prediction > 1.00) AS mp_gt1,

    COUNT(*) FILTER (WHERE sc.ra_error IS NULL AND sc.plate_id IS NOT NULL) AS raerr_null,
    COUNT(*) FILTER (WHERE sc.ra_error < 0) AS raerr_lt0,
    COUNT(*) FILTER (WHERE sc.ra_error = 0) AS raerr_eq0,
    COUNT(*) FILTER (WHERE sc.ra_error > 0 AND sc.ra_error <= 0.25) AS raerr_0_025,
    COUNT(*) FILTER (WHERE sc.ra_error > 0.25 AND sc.ra_error <= 0.50) AS raerr_025_050,
    COUNT(*) FILTER (WHERE sc.ra_error > 0.50 AND sc.ra_error <= 1.00) AS raerr_050_100,
    COUNT(*) FILTER (WHERE sc.ra_error > 1.00 AND sc.ra_error <= 2.00) AS raerr_100_200,
    COUNT(*) FILTER (WHERE sc.ra_error > 2.00 AND sc.ra_error <= 5.00) AS raerr_200_500,
    COUNT(*) FILTER (WHERE sc.ra_error > 5.00 AND sc.ra_error <= 10.00) AS raerr_500_1000,
    COUNT(*) FILTER (WHERE sc.ra_error > 10.00) AS raerr_gt1000,

    COUNT(*) FILTER (WHERE sc.dec_error IS NULL AND sc.plate_id IS NOT NULL) AS decerr_null,
    COUNT(*) FILTER (WHERE sc.dec_error < 0) AS decerr_lt0,
    COUNT(*) FILTER (WHERE sc.dec_error = 0) AS decerr_eq0,
    COUNT(*) FILTER (WHERE sc.dec_error > 0 AND sc.dec_error <= 0.25) AS decerr_0_025,
    COUNT(*) FILTER (WHERE sc.dec_error > 0.25 AND sc.dec_error <= 0.50) AS decerr_025_050,
    COUNT(*) FILTER (WHERE sc.dec_error > 0.50 AND sc.dec_error <= 1.00) AS decerr_050_100,
    COUNT(*) FILTER (WHERE sc.dec_error > 1.00 AND sc.dec_error <= 2.00) AS decerr_100_200,
    COUNT(*) FILTER (WHERE sc.dec_error > 2.00 AND sc.dec_error <= 5.00) AS decerr_200_500,
    COUNT(*) FILTER (WHERE sc.dec_error > 5.00 AND sc.dec_error <= 10.00) AS decerr_500_1000,
    COUNT(*) FILTER (WHERE sc.dec_error > 10.00) AS decerr_gt1000,

    COUNT(*) FILTER (WHERE sc.ra_icrs IS NULL AND sc.dec_icrs IS NULL AND sc.plate_id IS NOT NULL) AS coord_both_null,
    COUNT(*) FILTER (WHERE sc.ra_icrs IS NULL AND sc.dec_icrs IS NOT NULL) AS coord_ra_null_only,
    COUNT(*) FILTER (WHERE sc.ra_icrs IS NOT NULL AND sc.dec_icrs IS NULL) AS coord_dec_null_only,
    COUNT(*) FILTER (WHERE sc.ra_icrs >= 0 AND sc.ra_icrs < 360 AND sc.dec_icrs >= -90 AND sc.dec_icrs <= 90) AS coord_valid_icrs_bounds,
    COUNT(*) FILTER (WHERE sc.ra_icrs IS NOT NULL AND sc.dec_icrs IS NOT NULL AND NOT (sc.ra_icrs >= 0 AND sc.ra_icrs < 360 AND sc.dec_icrs >= -90 AND sc.dec_icrs <= 90)) AS coord_out_of_bounds,

    COUNT(*) FILTER (WHERE sc.annular_bin IS NULL AND sc.plate_id IS NOT NULL) AS annular_null,
    COUNT(*) FILTER (WHERE sc.annular_bin = 1) AS annular_1,
    COUNT(*) FILTER (WHERE sc.annular_bin = 2) AS annular_2,
    COUNT(*) FILTER (WHERE sc.annular_bin = 3) AS annular_3,
    COUNT(*) FILTER (WHERE sc.annular_bin = 4) AS annular_4,
    COUNT(*) FILTER (WHERE sc.annular_bin = 5) AS annular_5,
    COUNT(*) FILTER (WHERE sc.annular_bin = 6) AS annular_6,
    COUNT(*) FILTER (WHERE sc.annular_bin = 7) AS annular_7,
    COUNT(*) FILTER (WHERE sc.annular_bin = 8) AS annular_8,
    COUNT(*) FILTER (WHERE sc.annular_bin = 9) AS annular_9,
    COUNT(*) FILTER (WHERE sc.annular_bin < 1 OR sc.annular_bin > 9) AS annular_other
FROM selected AS s
LEFT JOIN applause_dr4.source_calib AS sc
  ON sc.plate_id = s.plate_id
 AND sc.scan_id = s.scan_id
 AND sc.process_id = s.process_id
 AND sc.solution_num = s.solution_num
GROUP BY s.key_id, s.plate_id, s.scan_id, s.process_id, s.solution_num
ORDER BY s.key_id;
-- END Q1_SELECTED_SCIENCE_KEY_AGGREGATES

-- BEGIN Q2_PHYSICAL_PLATE_PROCESSING_MULTIPLICITY
WITH plates(plate_id) AS (
    VALUES
    /*__Q2_VALUES__*/
)
SELECT
    p.plate_id,
    COUNT(sc.plate_id) AS all_processing_source_rows,
    COUNT(DISTINCT sc.scan_id) AS distinct_scans,
    COUNT(DISTINCT sc.process_id) AS distinct_processes,
    COUNT(DISTINCT (sc.process_id, sc.solution_num))
        FILTER (WHERE sc.plate_id IS NOT NULL)
        AS distinct_process_solution_nums,
    COUNT(DISTINCT (sc.scan_id, sc.process_id, sc.solution_num))
        FILTER (WHERE sc.plate_id IS NOT NULL)
        AS distinct_scan_process_solution_nums
FROM plates AS p
LEFT JOIN applause_dr4.source_calib AS sc
  ON sc.plate_id = p.plate_id
GROUP BY p.plate_id
ORDER BY p.plate_id;
-- END Q2_PHYSICAL_PLATE_PROCESSING_MULTIPLICITY
