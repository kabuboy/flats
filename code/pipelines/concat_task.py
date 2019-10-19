#!/usr/bin/env python3
""""
Pipeline to concatinate and dedup all scraping outputs
It concats data from each folder - sale and rent
and saves them on s3 in 'morizon-data/spider-name/concated' folder.
"""
import os
import logging as log

import pandas as pd

import utils
from common import PATHS, HOME_PATH, get_current_dt, logs_conf

log.basicConfig(**logs_conf)


def concat_csvs_to_parquet(in_path, out_path, spider_type):
    """
    Concat all files stored in 'in_path' directory and most current parquet file
    from 'out_path' directory. Save the output to 'out_path' directory.
    """
    # filter desc files
    in_path_content = os.listdir(f"{in_path}")
    log.info(f"Found {len(in_path_content)} files to concat.")
    paths_to_concat = [f for f in in_path_content if "desc" not in f]
    paths_to_concat = [f"{in_path}/{f}" for f in paths_to_concat]

    full_df = utils.concat_dfs(paths_to_concat)
    full_df = full_df.drop_duplicates("offer_id", keep="last")

    current_dt = get_current_dt()
    out_filepath = f"{out_path}/{spider_type}_concated_{current_dt}.parquet"
    log.info(f"Writing {out_filepath} ...")
    full_df.to_parquet(out_filepath, index=False)


log.info("Starting data concatination pipeline...")
for spider_type in PATHS:
    print(spider_type)
    in_path = PATHS[spider_type]["raw"]
    out_path = PATHS[spider_type]["concated"]
    log.info(f"Starting concating files for {spider_type}.")
    concat_csvs_to_parquet(in_path, out_path, spider_type)
    log.info(f"Successfully concated files for {spider_type}")
log.info("Finished data_concatination pipeline.")