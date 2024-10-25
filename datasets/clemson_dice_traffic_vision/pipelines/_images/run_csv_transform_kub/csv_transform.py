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
import shutil
import subprocess
import tarfile

import pandas as pd
from google.cloud import storage
from retrying import retry


@retry(stop_max_attempt_number=7, stop_max_delay=300000)
def main(
    source_url_gcs: str,
    source_file_batch_length: str,
    target_gcs_bucket: str,
    target_gcs_path: str,
    target_root_path: str,
    target_source_folder: str,
    target_unpack_folder: str,
    target_load_folder: str,
    target_batch_folder: str,
    project_id: str,
    pipeline_name: str,
    batch_group_size: str,
    batch_ordinal: str,
) -> None:
    generate_folder_hierarchy(
        target_root_path=target_root_path,
        target_source_folder=target_source_folder,
        target_unpack_folder=target_unpack_folder,
        target_load_folder=target_load_folder,
        target_batch_folder=target_batch_folder,
    )
    if pipeline_name == "transfer_source":
        copy_source_files_gcs_to_gcs(
            # source_bucket=source_client_bucket,
            source_bucket="gcs-public-data-trafficvision",
            destination_bucket=target_gcs_bucket,
            destination_folder=f"data/trafficvision/{target_source_folder}",
            file_type=".tar.gz",
            silent=True,
        )
    elif pipeline_name == "generate_batch_metadata_files":
        remove_gcs_path(
            gcs_bucket=target_gcs_bucket,
            gcs_path=f"{target_gcs_path}/{target_load_folder}",
        )
        remove_gcs_path(
            gcs_bucket=target_gcs_bucket,
            gcs_path=f"{target_gcs_path}/{target_batch_folder}",
        )
        generate_batch_metadata_files(
            project_id=project_id,
            source_gcs_folder_path=source_url_gcs,
            source_file_batch_length=source_file_batch_length,
            target_gcs_bucket=target_gcs_bucket,
            target_root_path=target_root_path,
            target_batch_folder=target_batch_folder,
            file_type=".tar.gz",
        )
    elif pipeline_name == "run_batch_data":
        process_batch_metadata_files(
            project_id=project_id,
            target_gcs_bucket=target_gcs_bucket,
            target_gcs_path=target_gcs_path,
            target_root_path=target_root_path,
            target_source_folder=target_source_folder,
            target_unpack_folder=target_unpack_folder,
            target_load_folder=target_load_folder,
            target_batch_folder=target_batch_folder,
            batch_gcs_path=f"{target_gcs_path}/{target_batch_folder}",
            batch_group_size=int(batch_group_size),
            batch_ordinal=int(batch_ordinal),
        )
    else:
        pass


def copy_source_files_gcs_to_gcs(
    source_bucket: str,
    destination_bucket: str,
    destination_folder: str,
    file_type: str,
    silent: bool = True,
) -> None:
    logging.info(
        f"Copying from gs://{source_bucket} to gs://{destination_bucket}/{destination_folder}"
    )
    subprocess.check_call("which gsutil", shell=True)
    cmd = f"gsutil -m cp -n gs://{source_bucket} gs://{destination_bucket}/{destination_folder}"
    if silent:
        cmd += " 2> /dev/null"
    subprocess.check_call([cmd], shell=True)


def process_batch_metadata_files(
    project_id: str,
    target_gcs_bucket: str,
    target_gcs_path: str,
    target_root_path: str,
    target_source_folder: str,
    target_unpack_folder: str,
    target_load_folder: str,
    target_batch_folder: str,
    batch_gcs_path: str,
    batch_group_size: int,
    batch_ordinal: int,
) -> None:
    logging.info("Collecting list of batch metadata files to process ...")
    storage_client = storage.Client(project_id)
    bucket_name = target_gcs_bucket
    bucket = storage_client.bucket(bucket_name)
    file_group_ordinal = 1
    for blob in bucket.list_blobs(prefix=batch_gcs_path):
        batch_filename = str(blob).split(",")[1].strip()
        if file_group_ordinal == batch_ordinal:
            process_batch(
                project_id=project_id,
                batch_filename=batch_filename,
                target_gcs_bucket=target_gcs_bucket,
                target_gcs_path=target_gcs_path,
                target_root_path=target_root_path,
                target_source_folder=target_source_folder,
                target_unpack_folder=target_unpack_folder,
                target_load_folder=target_load_folder,
                target_batch_folder=target_batch_folder,
            )
        else:
            pass
        file_group_ordinal += 1
        if file_group_ordinal > batch_group_size:
            file_group_ordinal = 1


def process_batch(
    project_id: str,
    batch_filename: str,
    target_gcs_bucket: str,
    target_gcs_path: str,
    target_root_path: str,
    target_source_folder: str,
    target_unpack_folder: str,
    target_load_folder: str,
    target_batch_folder: str,
) -> None:
    logging.info(f"Processing batch file {batch_filename} batches")
    download_file_gcs(
        project_id=project_id,
        source_location=f"gs://{target_gcs_bucket}/{batch_filename}",
        destination_folder=f"{target_root_path}/{target_batch_folder}",
    )
    batch_filename = (
        f"{target_root_path}/{target_batch_folder}/{os.path.basename(batch_filename)}"
    )
    df_filelist = pd.read_csv(batch_filename, sep="|")
    for gcs_source_file in df_filelist["pathname"]:
        filename = os.path.basename(gcs_source_file)
        guid = str(
            df_filelist[df_filelist["pathname"] == gcs_source_file]["guid"].values[0]
        ).strip()
        source_json_file = f"{target_root_path}/{target_unpack_folder}/{guid}/out.log"
        destination_json_file = f"{target_root_path}/{target_load_folder}/out{guid}.log"
        source_tar_file = f"{target_root_path}/{target_source_folder}/{filename}"
        download_file_gcs(
            project_id=project_id,
            source_location=gcs_source_file,
            destination_folder=f"{target_root_path}/{target_source_folder}",
        )
        with tarfile.open(source_tar_file) as file:
            file.extractall(path=f"{target_root_path}/{target_unpack_folder}")
        add_id_column(
            source_json_file=source_json_file,
            destination_json_file=destination_json_file,
            guid=guid,
        )
        upload_file_to_gcs(
            file_path=destination_json_file,
            gcs_bucket=target_gcs_bucket,
            gcs_path=f"{target_gcs_path}/{target_load_folder}/out{guid}.log",
        )
        os.unlink(source_tar_file)
        os.unlink(destination_json_file)
        shutil.rmtree(f"{target_root_path}/{target_unpack_folder}/{guid}")
        os.unlink(batch_filename)


def generate_folder_hierarchy(
    target_root_path: str,
    target_source_folder: str,
    target_unpack_folder: str,
    target_load_folder: str,
    target_batch_folder: str,
) -> None:
    if not os.path.exists(f"{target_root_path}"):
        logging.info(f"Creating folder {target_root_path}")
        os.makedirs(f"{target_root_path}")
    if not os.path.exists(f"{target_root_path}/{target_source_folder}"):
        logging.info(f"Creating folder {target_source_folder}")
        os.makedirs(f"{target_root_path}/{target_source_folder}")
    if not os.path.exists(f"{target_root_path}/{target_unpack_folder}"):
        logging.info(f"Creating folder {target_unpack_folder}")
        os.makedirs(f"{target_root_path}/{target_unpack_folder}")
    if not os.path.exists(f"{target_root_path}/{target_load_folder}"):
        logging.info(f"Creating folder {target_load_folder}")
        os.makedirs(f"{target_root_path}/{target_load_folder}")
    if not os.path.exists(f"{target_root_path}/{target_batch_folder}"):
        logging.info(f"Creating folder {target_batch_folder}")
        os.makedirs(f"{target_root_path}/{target_batch_folder}")


def generate_batch_metadata_files(
    project_id: str,
    source_gcs_folder_path: str,
    source_file_batch_length: int,
    target_gcs_bucket: str,
    target_root_path: str,
    target_batch_folder: str,
    file_type: str,
) -> None:
    logging.info("Collecting list of files to process ...")
    storage_client = storage.Client(project_id)
    bucket_name = str.split(source_gcs_folder_path, "gs://")[1].split("/")[0]
    bucket = storage_client.bucket(bucket_name)
    df_filelist = pd.DataFrame(columns=["pathname", "guid", "batchnumber"])
    total_number_files_in_bucket = count_files_in_gcs_bucket(
        project_id=project_id,
        source_gcs_folder_path=source_gcs_folder_path,
        file_type=".tar.gz",
    )
    file_counter = 0
    batch_number = 0
    prefix_folder = source_gcs_folder_path.replace("gs://", "").replace(
        f"{bucket_name}/", ""
    )
    for blob in bucket.list_blobs(prefix=prefix_folder):
        filename = str(blob).split(",")[1].strip()
        batch_number_zfill = str(batch_number).zfill(6)
        batch_metadata_file_path = f"{target_root_path}/{target_batch_folder}/batch_metadata-{batch_number_zfill}.txt"
        if filename.find(f"{file_type}") > 0 or file_type == "":
            filenm = os.path.basename(filename)
            path = f"{source_gcs_folder_path}/{filenm}"
            guid = str(filenm).replace(f"{file_type}", "")
            if (
                file_counter % int(source_file_batch_length) == 0
                or file_counter == total_number_files_in_bucket
            ):
                if batch_number > 0:
                    save_to_new_file(
                        df=df_filelist, file_path=batch_metadata_file_path, sep="|"
                    )
                    metadata_filename = os.path.basename(batch_metadata_file_path)
                    upload_file_to_gcs(
                        file_path=batch_metadata_file_path,
                        gcs_bucket=target_gcs_bucket,
                        gcs_path=f"{target_root_path}/{target_batch_folder}/{metadata_filename}",
                    )
                df_filelist = pd.DataFrame(columns=["pathname", "guid", "batchnumber"])
                batch_number += 1
                logging.info(
                    f"Generating metadata for batch {batch_number} file #{file_counter}"
                )
            df_filelist.loc[len(df_filelist)] = [path, guid, batch_number]
            file_counter += 1


def save_to_new_file(df: pd.DataFrame, file_path: str, sep: str = "|") -> None:
    logging.info(f"Saving data to target file.. {file_path} ...")
    df.to_csv(file_path, index=False, sep=sep)


def count_files_in_gcs_bucket(
    project_id: str, source_gcs_folder_path: str, file_type: str
) -> int:
    storage_client = storage.Client(project_id)
    bucket_name = str.split(source_gcs_folder_path, "gs://")[1].split("/")[0]
    bucket = storage_client.bucket(bucket_name)
    cnt_files = 0
    for blob in bucket.list_blobs():
        filename = str(blob).split(",")[1].strip()
        if os.path.basename(filename).find(f"{file_type}") > 0 or file_type == "":
            cnt_files += 1
    return cnt_files


def download_file_gcs(
    project_id: str, source_location: str, destination_folder: str
) -> None:
    object_name = os.path.basename(source_location)
    dest_object = f"{destination_folder}/{object_name}"
    storage_client = storage.Client(project_id)
    bucket_name = str.split(source_location, "gs://")[1].split("/")[0]
    bucket = storage_client.bucket(bucket_name)
    source_object_path = str.split(source_location, f"gs://{bucket_name}/")[1]
    blob = bucket.blob(source_object_path)
    blob.download_to_filename(dest_object)


def add_id_column(source_json_file: str, destination_json_file: str, guid: str):
    shutil.copyfile(source_json_file, destination_json_file)
    cmd = (
        f'sed -i -e \'s/{{\\"frame\\"/{{"id": \\"{guid}\\", \\"frame\\"/g\'{destination_json_file}'
        # 'sed -i -e \'s/{\\"frame\\"/{"id": "'
        # + guid
        # + '"\, "frame"/g\' '
        # + destination_json_file
    )
    logging.info(f"cmd = {cmd}")
    subprocess.check_call([cmd], shell=True)


def upload_file_to_gcs(file_path: pathlib.Path, gcs_bucket: str, gcs_path: str) -> None:
    storage_client = storage.Client()
    bucket = storage_client.bucket(gcs_bucket)
    blob = bucket.blob(gcs_path)
    blob.upload_from_filename(file_path)


def remove_gcs_path(gcs_bucket: str, gcs_path: str) -> None:
    drop_path = os.path.split(gcs_path)[0]
    logging.info(f"Removing files from GCS path {drop_path}")
    storage_client = storage.Client()
    bucket = storage_client.bucket(gcs_bucket)
    bucket.delete_blobs(blobs=list(bucket.list_blobs(prefix=f"{drop_path}/")))


if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)

    main(
        source_url_gcs=os.environ.get("SOURCE_URL_GCS", ""),
        source_file_batch_length=os.environ.get("SOURCE_FILE_BATCH_LENGTH", ""),
        target_gcs_bucket=os.environ.get("TARGET_GCS_BUCKET", ""),
        target_gcs_path=os.environ.get("TARGET_GCS_PATH", ""),
        target_root_path=os.environ.get("TARGET_ROOT_PATH", ""),
        target_source_folder=os.environ.get("TARGET_SOURCE_FOLDER", ""),
        target_unpack_folder=os.environ.get("TARGET_UNPACK_FOLDER", ""),
        target_load_folder=os.environ.get("TARGET_LOAD_FOLDER", ""),
        target_batch_folder=os.environ.get("TARGET_BATCH_FOLDER", ""),
        project_id=os.environ.get("PROJECT_ID", ""),
        pipeline_name=os.environ.get("PIPELINE_NAME", ""),
        batch_group_size=os.environ.get("BATCH_GROUP_SIZE", 1),
        batch_ordinal=os.environ.get("BATCH_ORDINAL", 1),
    )
