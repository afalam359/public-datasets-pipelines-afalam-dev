# Copyright 2021 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import os
import pathlib

import pandas as pd
from google.cloud import storage


def main(
    source_url: str,
    source_file: pathlib.Path,
    target_file: pathlib.Path,
    chunksize: str,
    target_gcs_bucket: str,
    target_gcs_path: str,
) -> None:

    logging.info(
        "International Database (Country Names - Midyear Population, by Age and Country Code) Delivery process started"
    )

    pathlib.Path("./files").mkdir(parents=True, exist_ok=True)

    df_pop = obtain_source_data(
        source_url, source_file, ["country_code", "year"], "_pop_data.csv", 0, ","
    )
    df_country = obtain_source_data(
        source_url, source_file, ["country_code"], "_country_data.csv", 1, ","
    )

    df = pd.merge(
        df_pop,
        df_country,
        left_on="country_code",
        right_on="country_code",
        how="left",
    )

    df = unpivot_data(df)
    df = resolve_sex(df)
    df = rename_headers(df)
    df = reorder_headers(df)

    save_to_new_file(df, target_file, ",")
    upload_file_to_gcs(target_file, target_gcs_bucket, target_gcs_path)

    logging.info(
        "International Database (Country Names - Midyear Population, by Age and Country Code) Delivery process completed"
    )


def unpivot_data(df: pd.DataFrame) -> pd.DataFrame:
    logging.info("Unpivoting Data")
    df["pop_exp"] = df.apply(lambda x: x.population.split(","), axis=1)
    df_exp_unpivot = df.explode("pop_exp").reset_index().drop(columns="index", axis=1)
    df_exp_unpivot["age_exp"] = df_exp_unpivot.groupby("key_val_x").cumcount()
    df_exp_unpivot = df_exp_unpivot.drop(columns=["population", "age"])

    return df_exp_unpivot


def resolve_sex(df: pd.DataFrame) -> pd.DataFrame:
    logging.info("Resolving gender data point")
    df = df.replace(to_replace={"sex": {2: "Male", 3: "Female"}})

    return df


def rename_headers(df: pd.DataFrame) -> pd.DataFrame:
    logging.info("Renaming headers")
    header_names = {
        "country_code": "country_code",
        "country_name": "country_name",
        "year": "year",
        "sex": "sex",
        "pop_exp": "population",
        "age_exp": "age",
    }
    df = df.rename(columns=header_names)

    return df


def obtain_source_data(
    source_url: str,
    source_file: str,
    key_list: list,
    file_suffix: str,
    path_ordinal: int,
    separator: str = ",",
) -> pd.DataFrame:
    source_data_filepath = str(source_file).replace(".csv", file_suffix)
    download_file_gs(
        source_url.split(",")[path_ordinal].replace('"', "").strip(),
        source_data_filepath,
    )
    df = pd.read_csv(
        source_data_filepath,
        engine="python",
        encoding="utf-8",
        quotechar='"',  # string separator, typically double-quotes
        sep=",",  # data column separator, typically ","
    )
    df = add_key(df, key_list)
    df.drop_duplicates(subset=["key"], keep="last", inplace=True, ignore_index=False)

    return df


def download_file_gs(source_url: str, source_file: pathlib.Path) -> None:
    logging.info(f"Downloading {source_url} to {source_file}")
    with open(source_file, "wb+") as file_obj:
        storage.Client().download_blob_to_file(source_url, file_obj)


def add_key(df: pd.DataFrame, key_list: list) -> pd.DataFrame:
    logging.info(f"Adding key column(s) {key_list}")
    df["key"] = ""
    for key in key_list:
        df["key"] = df.apply(
            lambda x: str(x[key])
            if not str(x["key"])
            else str(x["key"]) + "-" + str(x[key]),
            axis=1,
        )
    df["key_val"] = df["key"]

    return df


def reorder_headers(df: pd.DataFrame) -> pd.DataFrame:
    logging.info("Reordering headers..")
    df = df[["country_code", "country_name", "year", "sex", "population", "age"]]

    return df


def save_to_new_file(df, file_path, sep="|") -> None:
    logging.info(f"Saving to file {file_path} separator='{sep}'")
    df.to_csv(file_path, sep=sep, index=False)


def upload_file_to_gcs(file_path: pathlib.Path, gcs_bucket: str, gcs_path: str) -> None:
    logging.info(f"Uploading to GCS {gcs_bucket} in {gcs_path}")
    storage_client = storage.Client()
    bucket = storage_client.bucket(gcs_bucket)
    blob = bucket.blob(gcs_path)
    blob.upload_from_filename(file_path)


if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)

    main(
        source_url=os.environ["SOURCE_URL"],
        source_file=pathlib.Path(os.environ["SOURCE_FILE"]).expanduser(),
        target_file=pathlib.Path(os.environ["TARGET_FILE"]).expanduser(),
        chunksize=os.environ["CHUNKSIZE"],
        target_gcs_bucket=os.environ["TARGET_GCS_BUCKET"],
        target_gcs_path=os.environ["TARGET_GCS_PATH"],
    )
