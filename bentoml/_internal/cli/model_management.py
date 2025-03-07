import json
import typing as t
import logging

import yaml
import click
from simple_di import inject
from simple_di import Provide
from rich.table import Table
from rich.console import Console

from bentoml.models import import_model

from ..utils import calc_dir_size
from ..utils import human_readable_size
from .click_utils import _is_valid_bento_tag
from .click_utils import _is_valid_bento_name
from ..yatai_client import yatai_client
from ..configuration.containers import BentoMLContainer

if t.TYPE_CHECKING:
    from ..models import ModelStore

logger = logging.getLogger(__name__)


def parse_delete_targets_argument_callback(
    ctx, params, value
):  # pylint: disable=unused-argument
    if value is None:
        return value
    delete_targets = value.split(",")
    delete_targets = list(map(str.strip, delete_targets))
    for delete_target in delete_targets:
        if not (
            _is_valid_bento_tag(delete_target) or _is_valid_bento_name(delete_target)
        ):
            raise click.BadParameter(
                "Bad formatting. Please present a valid bento bundle name or "
                '"name:version" tag. For list of bento bundles, separate delete '
                'targets by ",", for example: "my_service:v1,my_service:v2,'
                'classifier"'
            )
    return delete_targets


@inject
def add_model_management_commands(
    cli,
    model_store: "ModelStore" = Provide[BentoMLContainer.model_store],
):
    @cli.group(name="models")
    def model_cli():
        """Model Management"""

    @model_cli.command()
    @click.argument("model_tag", type=click.STRING)
    @click.option(
        "-o",
        "--output",
        type=click.Choice(["json", "yaml", "path"]),
        default="yaml",
    )
    def get(model_tag, output):
        """Print Model details by providing the model_tag

        \b
        bentoml models get FraudDetector:latest
        bentoml models get --output=json FraudDetector:20210709_DE14C9
        """
        model = model_store.get(model_tag)
        console = Console()

        if output == "path":
            console.print(model.path)
        elif output == "json":
            info = json.dumps(model.info.to_dict(), indent=2, default=str)
            console.print_json(info)
        else:
            info = yaml.dump(model.info, indent=2)
            console.print(info)

    @model_cli.command(name="list")
    @click.argument("model_name", type=click.STRING, required=False)
    @click.option(
        "-o",
        "--output",
        type=click.Choice(["json", "yaml", "table"]),
        default="table",
    )
    @click.option(
        "--no-trunc",
        is_flag=False,
        help="Don't truncate the output",
    )
    def list_models(model_name, output, no_trunc):
        """List Models in local store

        \b
        # show all models saved
        > bentoml models list

        \b
        # show all verions of bento with the name FraudDetector
        > bentoml models list FraudDetector
        """
        models = model_store.list(model_name)
        res = [
            {
                "tag": str(model.tag),
                "module": model.info.module,
                "path": model.path,
                "size": human_readable_size(calc_dir_size(model.path)),
                "creation_time": model.info.creation_time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            for model in sorted(
                models, key=lambda x: x.info.creation_time, reverse=True
            )
        ]
        if output == "json":
            info = json.dumps(res, indent=2)
            print(info)
        elif output == "yaml":
            info = yaml.safe_dump(res, indent=2)
            print(info)
        else:
            table = Table(box=None)
            table.add_column("Tag")
            table.add_column("Module")
            table.add_column("Path")
            table.add_column("Size")
            table.add_column("Creation Time")
            for model in res:
                table.add_row(
                    model["tag"],
                    model["module"],
                    model["path"],
                    model["size"],
                    model["creation_time"],
                )
            console = Console()
            console.print(table)

    @model_cli.command()
    @click.argument(
        "delete_targets",
        type=click.STRING,
        callback=parse_delete_targets_argument_callback,
        required=True,
    )
    @click.option(
        "-y",
        "--yes",
        "--assume-yes",
        is_flag=True,
        help="Skip confirmation when deleting a specific model",
    )
    def delete(
        delete_targets,
        yes,
    ):
        """Delete Model in local model store.

        Specify target Models to remove:

        \b
        * Delete single model by "name:version", e.g: `bentoml models delete IrisClassifier:v1`
        * Bulk delete all models with a specific name, e.g.: `bentoml models delete IrisClassifier`
        * Bulk delete multiple models by name and version, separated by ",", e.g.: `benotml models delete Irisclassifier:v1,MyPredictService:v2`
        """  # noqa

        def delete_target(target):
            to_delete_models = model_store.list(target)

            for model in to_delete_models:
                if yes:
                    delete_confirmed = True
                else:
                    delete_confirmed = click.confirm(f"delete model {model.tag}?")

                if delete_confirmed:
                    model_store.delete(model.tag)
                    logger.info(f"{model} deleted")

        for target in delete_targets:
            delete_target(target)

    @model_cli.command()
    @click.argument("model_tag", type=click.STRING)
    @click.argument("out_path", type=click.STRING, default="", required=False)
    def export(model_tag, out_path):
        """Export Model files to an archive file

        arguments:

        \b
        MODEL_TAG: model identifier
        OUT_PATH: output path of exported model.
          If this argument is not provided, model is exported to name-version.bentomodel in the current directory.
          Besides native .bentomodel format, we also support formats like tar('tar'), tar.gz ('gz'), tar.xz ('xz'), tar.bz2 ('bz2'), and zip.

        examples:

        \b
        bentoml models export FraudDetector:latest
        bentoml models export FraudDetector:latest ./my_model.bentomodel
        bentoml models export FraudDetector:20210709_DE14C9 ./my_model.bentomodel
        bentoml models export FraudDetector:20210709_DE14C9 s3://mybucket/models/my_model.bentomodel
        """
        bentomodel = model_store.get(model_tag)
        bentomodel.export(out_path)
        logger.info(f"{bentomodel} exported to {out_path}")

    @model_cli.command(name="import")
    @click.argument("model_path", type=click.STRING)
    def import_from(model_path):
        """Import a previously exported Model archive file

        bentoml models import ./my_model.bentomodel
        bentoml models import s3://mybucket/models/my_model.bentomodel
        """
        bentomodel = import_model(model_path)
        logger.info(f"{bentomodel} imported")

    @model_cli.command(
        help="Pull Model from a yatai server",
    )
    @click.argument("model_tag", type=click.STRING)
    @click.option(
        "-f",
        "--force",
        is_flag=True,
        default=False,
        help="Force pull from yatai to local and overwrite even if it already exists in local",
    )
    def pull(model_tag: str, force: bool):
        yatai_client.pull_model(model_tag, force=force)

    @model_cli.command(help="Push Model to a yatai server")
    @click.argument("model_tag", type=click.STRING)
    @click.option(
        "-f",
        "--force",
        is_flag=True,
        default=False,
        help="Forced push to yatai even if it exists in yatai",
    )
    def push(model_tag: str, force: bool):
        model_obj = model_store.get(model_tag)
        if not model_obj:
            raise click.ClickException(f"Model {model_tag} not found in local store")
        yatai_client.push_model(model_obj, force=force)
