"""
APIs for retrieving, updating, creating, and deleting Individual records
"""
import json
import re
from collections import defaultdict
from datetime import datetime
from django.contrib.auth.models import User
from django.db.models import prefetch_related_objects

from reference_data.models import HumanPhenotypeOntology
from seqr.models import Individual, Family
from seqr.utils.gene_utils import get_genes
from seqr.views.utils.file_utils import save_uploaded_file, load_uploaded_file
from seqr.views.utils.json_to_orm_utils import update_individual_from_json, update_model_from_json
from seqr.views.utils.json_utils import create_json_response, _to_snake_case
from seqr.views.utils.orm_to_json_utils import _get_json_for_model, _get_json_for_individuals, add_individual_hpo_details, \
    _get_json_for_families, get_json_for_rna_seq_outliers, get_project_collaborators_by_username
from seqr.views.utils.pedigree_info_utils import parse_pedigree_table, validate_fam_file_records, JsonConstants, ErrorsWarningsException
from seqr.views.utils.permissions_utils import get_project_and_check_permissions, check_project_permissions, \
    get_project_and_check_pm_permissions, login_and_policies_required, has_project_permissions, project_has_anvil, \
    is_internal_anvil_project
from seqr.views.utils.individual_utils import delete_individuals, get_parsed_feature, add_or_update_individuals_and_families


_SEX_TO_EXPORTED_VALUE = dict(Individual.SEX_LOOKUP)
_SEX_TO_EXPORTED_VALUE['U'] = ''

__AFFECTED_TO_EXPORTED_VALUE = dict(Individual.AFFECTED_STATUS_LOOKUP)
__AFFECTED_TO_EXPORTED_VALUE['U'] = ''


@login_and_policies_required
def update_individual_handler(request, individual_guid):
    """Updates a single field in an Individual record.

    Args:
        request (object): Django HTTP Request object.
        individual_guid (string): GUID of the Individual.

    Request:
        body should be a json dictionary like: { 'value': xxx }

    Response:
        json dictionary representing the updated individual like:
            {
                <individualGuid> : {
                    individualId: xxx,
                    sex: xxx,
                    affected: xxx,
                    ...
                }
            }
    """

    individual = Individual.objects.get(guid=individual_guid)

    project = individual.family.project

    check_project_permissions(project, request.user)
    can_edit = has_project_permissions(project, request.user, can_edit=True)

    request_json = json.loads(request.body)
    update_json = request_json if can_edit else {k: v for k, v in request_json.items() if k in {'notes'}}

    update_individual_from_json(individual, update_json, user=request.user, allow_unknown_keys=True)
    individual_json = _get_json_for_model(individual, user=request.user)
    individual_json['displayName'] = individual_json['displayName'] or individual_json['individualId']

    return create_json_response({
        individual.guid: individual_json
    })



@login_and_policies_required
def update_individual_hpo_terms(request, individual_guid):
    """Updates features fields for the given Individual
    """

    individual = Individual.objects.get(guid=individual_guid)

    project = individual.family.project

    check_project_permissions(project, request.user, can_edit=True)

    request_json = json.loads(request.body)

    feature_fields = ['features', 'absentFeatures', 'nonstandardFeatures', 'absentNonstandardFeatures']
    update_json = {
        key: [get_parsed_feature(feature) for feature in request_json[key]] if request_json.get(key) else None
        for key in feature_fields
    }
    update_model_from_json(individual, update_json, user=request.user)

    individual_json = {k: getattr(individual, _to_snake_case(k)) for k in feature_fields}
    add_individual_hpo_details([individual_json])

    return create_json_response({
        individual.guid: individual_json
    })


def _anvil_project_can_edit_pedigree(project, user):
    return project_has_anvil(project) and has_project_permissions(project, user, can_edit=True) and not \
        is_internal_anvil_project(project)


@login_and_policies_required
def edit_individuals_handler(request, project_guid):
    """Modify one or more Individual records.

    Args:
        request (object): Django HTTP Request object.
        project_guid (string): GUID of project that contains these individuals.

    Request:
        body should be a json dictionary that contains a 'individuals' list that includes the individuals to update,
         represented by dictionaries of their guid and fields to update -
        for example:
            {
                'individuals': [
                    { 'individualGuid': <individualGuid1>, 'paternalId': <paternalId>, 'affected': 'A' },
                    { 'individualGuid': <individualGuid1>, 'sex': 'U' },
                    ...
                [
            }

    Response:
        json dictionary representing the updated individual(s) like:
            {
                <individualGuid1> : { individualId: xxx, sex: xxx, affected: xxx, ...},
                <individualGuid2> : { individualId: xxx, sex: xxx, affected: xxx, ...},
                ...
            }
    """

    project = get_project_and_check_pm_permissions(project_guid, request.user,
                                                   override_permission_func=_anvil_project_can_edit_pedigree)

    request_json = json.loads(request.body)

    modified_individuals_list = request_json.get('individuals')
    if modified_individuals_list is None:
        return create_json_response(
            {}, status=400, reason="'individuals' not specified")

    update_individuals = {ind['individualGuid']: ind for ind in modified_individuals_list}
    update_individual_models = {ind.guid: ind for ind in Individual.objects.filter(guid__in=update_individuals.keys()).prefetch_related('family')}
    parent_guids = set()
    for modified_ind in modified_individuals_list:
        model = update_individual_models[modified_ind['individualGuid']]
        if modified_ind[JsonConstants.INDIVIDUAL_ID_COLUMN] != model.individual_id:
            modified_ind[JsonConstants.PREVIOUS_INDIVIDUAL_ID_COLUMN] = model.individual_id
        if not (modified_ind.get('familyId') or modified_ind.get('family')):
            modified_ind['familyId'] = model.family.family_id
        if modified_ind.get('paternalGuid'):
            parent_guids.add(modified_ind['paternalGuid'])
        if modified_ind.get('maternalGuid'):
            parent_guids.add(modified_ind['maternalGuid'])

    errors = []
    if parent_guids:
        related_individuals = Individual.objects.filter(guid__in=parent_guids)
        parents_by_guid = {i.guid: i for i in related_individuals}
        for modified_ind in modified_individuals_list:
            _set_parent_relationships(modified_ind, parents_by_guid, 'paternalGuid', 'father', 'paternalId', errors)
            _set_parent_relationships(modified_ind, parents_by_guid, 'maternalGuid', 'mother', 'maternalId', errors)
    else:
        modified_family_ids = {ind.get('familyId') or ind['family']['familyId'] for ind in modified_individuals_list}
        modified_family_ids.update({ind.family.family_id for ind in update_individual_models.values()})
        related_individuals = Individual.objects.filter(family__family_id__in=modified_family_ids, family__project=project)
    related_individuals = related_individuals.exclude(guid__in=update_individuals.keys())
    related_individuals_json = _get_json_for_individuals(related_individuals, project_guid=project_guid, family_fields=['family_id'])
    individuals_list = modified_individuals_list + list(related_individuals_json)

    validate_fam_file_records(individuals_list, fail_on_warnings=True, errors=errors)

    return _update_and_parse_individuals_and_families(
        project, modified_individuals_list, user=request.user
    )


@login_and_policies_required
def delete_individuals_handler(request, project_guid):
    """Delete one or more Individual records.

    Args:
        request (object): Django HTTP Request object.
        project_guid (string): GUID of project that contains these individuals.

    Request:
        body should be a json dictionary that contains a 'recordIdsToDelete' list of individual
        GUIDs to delete - for example:
            {
                'form': {
                    'recordIdsToDelete': [
                        <individualGuid1>,
                        <individualGuid2>,
                        ...
                    }
                }
            }

    Response:
        json dictionary with the deleted GUIDs mapped to None:
            {
                <individualGuid1> : None,
                <individualGuid2> : None,
                ...
            }
    """

    # validate request
    project = get_project_and_check_pm_permissions(project_guid, request.user,
                                                   override_permission_func=_anvil_project_can_edit_pedigree)

    request_json = json.loads(request.body)
    individuals_list = request_json.get('individuals')
    if individuals_list is None:
        return create_json_response(
            {}, status=400, reason="Invalid request: 'individuals' not in request_json")

    individual_guids_to_delete = [ind['individualGuid'] for ind in individuals_list]

    # delete the individuals
    families_with_deleted_individuals = delete_individuals(project, individual_guids_to_delete, request.user)

    deleted_individuals_by_guid = {
        individual_guid: None for individual_guid in individual_guids_to_delete
    }

    families_by_guid = {
        family['familyGuid']: family for family in
        _get_json_for_families(families_with_deleted_individuals, request.user, add_individual_guids_field=True)
    } # families whose list of individuals may have changed

    # send response
    return create_json_response({
        'individualsByGuid': deleted_individuals_by_guid,
        'familiesByGuid': families_by_guid,
    })


@login_and_policies_required
def receive_individuals_table_handler(request, project_guid):
    """Handler for the initial upload of an Excel or .tsv table of individuals. This handler
    parses the records, but doesn't save them in the database. Instead, it saves them to
    a temporary file and sends a 'uploadedFileId' representing this file back to the client. If/when the
    client then wants to 'apply' this table, it can send the uploadedFileId to the
    save_individuals_table(..) handler to actually save the data in the database.

    Args:
        request (object): Django request object
        project_guid (string): project GUID
    """

    project = get_project_and_check_pm_permissions(project_guid, request.user)

    warnings = []
    def process_records(json_records, filename='ped_file'):
        pedigree_records, ped_warnings = parse_pedigree_table(json_records, filename, user=request.user, project=project)
        nonlocal warnings
        warnings += ped_warnings
        return pedigree_records

    try:
        uploaded_file_id, filename, json_records = save_uploaded_file(request, process_records=process_records)
    except ValueError as e:
        return create_json_response({'errors': [str(e)], 'warnings': []}, status=400, reason=str(e))

    if warnings:
        # If there are warnings, it might be because the upload referenced valid existing individuals and there is no
        # issue, or because it referenced individuals that actually don't exist, so re-validate with all individuals
        family_ids = {r[JsonConstants.FAMILY_ID_COLUMN] for r in json_records}
        individual_ids = {r[JsonConstants.INDIVIDUAL_ID_COLUMN] for r in json_records}

        related_individuals = Individual.objects.filter(
            family__family_id__in=family_ids, family__project=project).exclude(individual_id__in=individual_ids)
        related_individuals_json = _get_json_for_individuals(
            related_individuals, project_guid=project_guid, family_fields=['family_id'])

        validate_fam_file_records(json_records + list(related_individuals_json), fail_on_warnings=True)

    # send back some stats
    individual_ids_by_family = defaultdict(set)
    for r in json_records:
        if r.get(JsonConstants.PREVIOUS_INDIVIDUAL_ID_COLUMN):
            individual_ids_by_family[r[JsonConstants.FAMILY_ID_COLUMN]].add(
                (r[JsonConstants.PREVIOUS_INDIVIDUAL_ID_COLUMN], True)
            )
        else:
            individual_ids_by_family[r[JsonConstants.FAMILY_ID_COLUMN]].add(
                (r[JsonConstants.INDIVIDUAL_ID_COLUMN], False)
            )

    num_individuals = sum([len(indiv_ids) for indiv_ids in individual_ids_by_family.values()])
    num_existing_individuals = 0
    missing_prev_ids = []
    for family_id, indiv_ids in individual_ids_by_family.items():
        existing_individuals = {i.individual_id for i in Individual.objects.filter(
            individual_id__in=[indiv_id for (indiv_id, _) in indiv_ids], family__family_id=family_id, family__project=project
        ).only('individual_id')}
        num_existing_individuals += len(existing_individuals)
        missing_prev_ids += [indiv_id for (indiv_id, is_previous) in indiv_ids if is_previous and indiv_id not in existing_individuals]
    num_individuals_to_create = num_individuals - num_existing_individuals
    if missing_prev_ids:
        return create_json_response(
            {'errors': [
                'Could not find individuals with the following previous IDs: {}'.format(', '.join(missing_prev_ids))
            ], 'warnings': []},
            status=400, reason='Invalid input')

    family_ids = set(r[JsonConstants.FAMILY_ID_COLUMN] for r in json_records)
    num_families = len(family_ids)
    num_existing_families = Family.objects.filter(family_id__in=family_ids, project=project).count()
    num_families_to_create = num_families - num_existing_families

    info = [
        "{num_families} families, {num_individuals} individuals parsed from {filename}".format(
            num_families=num_families, num_individuals=num_individuals, filename=filename
        ),
        "{} new families, {} new individuals will be added to the project".format(num_families_to_create, num_individuals_to_create),
        "{} existing individuals will be updated".format(num_existing_individuals),
    ]

    response = {
        'uploadedFileId': uploaded_file_id,
        'errors': [],
        'warnings': [],
        'info': info,
    }
    return create_json_response(response)


@login_and_policies_required
def save_individuals_table_handler(request, project_guid, upload_file_id):
    """Handler for 'save' requests to apply Individual tables previously uploaded through receive_individuals_table(..)

    Args:
        request (object): Django request object
        project_guid (string): project GUID
        uploadedFileId (string): a token sent to the client by receive_individuals_table(..)
    """
    project = get_project_and_check_pm_permissions(project_guid, request.user)

    json_records = load_uploaded_file(upload_file_id)
    return _update_and_parse_individuals_and_families(project, individual_records=json_records, user=request.user)


def _update_and_parse_individuals_and_families(project, individual_records, user):
    pedigree_json = add_or_update_individuals_and_families(project, individual_records, user)
    return create_json_response(pedigree_json)


def _set_parent_relationships(record, parents_by_guid, guid_key, parent_key, parent_id_key, errors):
    parent_guid = record.get(guid_key)
    new_parent = parents_by_guid.get(parent_guid)
    if parent_guid and not new_parent:
        errors.append(f'Invalid parental guid {parent_guid}')
        return
    record.update({
        parent_key: new_parent,
        parent_id_key: new_parent.individual_id if new_parent else None,
    })


FAMILY_ID_COL = 'family_id'
INDIVIDUAL_ID_COL = 'individual_id'
INDIVIDUAL_GUID_COL = 'individual_guid'
HPO_TERM_NUMBER_COL = 'hpo_number'
AFFECTED_FEATURE_COL = 'affected'
FEATURES_COL = 'features'
ABSENT_FEATURES_COL = 'absent_features'
BIRTH_COL = 'birth_year'
DEATH_COL = 'death_year'
ONSET_AGE_COL = 'onset_age'
NOTES_COL = 'notes'
ASSIGNED_ANALYST_COL = 'assigned_analyst'
CONSANGUINITY_COL = 'consanguinity'
AFFECTED_REL_COL = 'affected_relatives'
EXP_INHERITANCE_COL = 'expected_inheritance'
MAT_ETHNICITY_COL = 'maternal_ethnicity'
PAT_ETHNICITY_COL = 'paternal_ethnicity'
DISORDERS_COL = 'disorders'
REJECTED_GENES_COL = 'rejected_genes'
CANDIDATE_GENES_COL =  'candidate_genes'
# assisted reproduction fields
AR_FM_COL = 'ar_fertility_meds'
AR_IUI_COL = 'ar_iui'
AR_IVF_COL = 'ar_ivf'
AR_ICSI_COL = 'ar_icsi'
AR_SURROGACY_COL = 'ar_surrogacy'
AR_DEGG_COL = 'ar_donoregg'
AR_DSPERM_COL = 'ar_donorsperm'

def _bool_value(val):
    if isinstance(val, bool):
        return val
    if val.lower() == 'true':
        return True
    elif val.lower() == 'false':
        return False
    raise ValueError

def _array_value(val):
    if isinstance(val, list):
        return val
    return [o.strip() for o in val.split(',')]

def _gene_value(val):
    gene_det = val.split('--')
    gene = {'gene': gene_det[0].strip()}
    if len(gene_det) > 1:
        gene['comments'] = gene_det[1].strip().lstrip('(').rstrip(')')
    return gene

def _gene_list_value(val):
    if isinstance(val, list):
        return val
    seperator_escaped_val = ''.join(m.replace(',', ';') if not m.startswith('(') else m for m in re.split('(\([^)]+\))', val))
    return [_gene_value(o) for o in seperator_escaped_val.split(';')]


INDIVIDUAL_METADATA_FIELDS = {
    FEATURES_COL: lambda val: [{'id': feature} for feature in val],
    ABSENT_FEATURES_COL: lambda val: [{'id': feature} for feature in val],
    BIRTH_COL: int,
    DEATH_COL: int,
    ONSET_AGE_COL: lambda val: Individual.ONSET_AGE_REVERSE_LOOKUP[val],
    NOTES_COL: str,
    CONSANGUINITY_COL: _bool_value,
    AFFECTED_REL_COL: _bool_value,
    EXP_INHERITANCE_COL: lambda val: [Individual.INHERITANCE_REVERSE_LOOKUP[o] for o in _array_value(val)],
    AR_FM_COL: _bool_value,
    AR_IUI_COL: _bool_value,
    AR_IVF_COL: _bool_value,
    AR_ICSI_COL: _bool_value,
    AR_SURROGACY_COL: _bool_value,
    AR_DEGG_COL: _bool_value,
    AR_DSPERM_COL: _bool_value,
    MAT_ETHNICITY_COL: _array_value,
    PAT_ETHNICITY_COL: _array_value,
    DISORDERS_COL: _array_value,
    REJECTED_GENES_COL: _gene_list_value,
    CANDIDATE_GENES_COL: _gene_list_value,
}

def _get_year(val):
    return datetime.strptime(val, '%Y-%m-%d').year

def _nested_val(nested_key):
    return lambda val: val.get(nested_key)

def _get_phenotips_features(observed):
    def get_observed_features(features):
        return [feature['id'] for feature in features if feature['observed'] == observed]
    return get_observed_features

PHENOTIPS_JSON_FIELD_MAP = {
    'family_id': [(FAMILY_ID_COL, None)],
    'external_id': [(INDIVIDUAL_ID_COL, None)],
    'features': [
        (FEATURES_COL, _get_phenotips_features('yes')),
        (ABSENT_FEATURES_COL, _get_phenotips_features('no')),
    ],
    'date_of_birth': [(BIRTH_COL, _get_year)],
    'date_of_death': [(DEATH_COL, _get_year)],
    'global_age_of_onset': [(ONSET_AGE_COL, lambda val: val[0]['label'])],
    'family_history': [
        (CONSANGUINITY_COL, _nested_val('consanguinity')),
        (AFFECTED_REL_COL, _nested_val('affectedRelatives')),
    ],
    'global_mode_of_inheritance': [(EXP_INHERITANCE_COL, lambda val: [o['label'] for o in val])],
    'prenatal_perinatal_history': [
        (AR_FM_COL, _nested_val('assistedReproduction_fertilityMeds')),
        (AR_IUI_COL, _nested_val('assistedReproduction_iui')),
        (AR_IVF_COL, _nested_val('ivf')),
        (AR_ICSI_COL, _nested_val('icsi')),
        (AR_SURROGACY_COL, _nested_val('assistedReproduction_surrogacy')),
        (AR_DEGG_COL, _nested_val('assistedReproduction_donoregg')),
        (AR_DSPERM_COL, _nested_val('assistedReproduction_donorsperm')),
    ],
    'ethnicity': [
        (MAT_ETHNICITY_COL, _nested_val('maternal_ethnicity')),
        (PAT_ETHNICITY_COL, _nested_val('paternal_ethnicity')),
    ],
    'disorders': [(DISORDERS_COL, lambda val: [int(d['id'].lstrip('MIM:')) for d in val])],
    'genes': [(CANDIDATE_GENES_COL, None)],
    'rejectedGenes': [(REJECTED_GENES_COL, None)],
}

def _parse_phenotips_record(row):
    record = {}
    for k, formatters in PHENOTIPS_JSON_FIELD_MAP.items():
        val = row.get(k)
        if val:
            for col, formatter in formatters:
                field_val = formatter(val) if formatter else val
                if field_val is not None:
                    record[col] = field_val
    return record

@login_and_policies_required
def receive_individuals_metadata_handler(request, project_guid):
    """
    Handler for bulk update of hpo terms and other individual metadata . This handler parses the records, but
    doesn't save them in the database. Instead, it saves them to a temporary file and sends a 'uploadedFileId'
    representing this file back to the client.

    Args:
        request (object): Django request object
        project_guid (string): project GUID
    """

    project = get_project_and_check_permissions(project_guid, request.user)

    def process_records(json_records, filename=''):
        records, errors, warnings = _process_hpo_records(json_records, filename, project, request.user)
        if errors:
            raise ErrorsWarningsException(errors, warnings)
        return records, warnings

    try:
        uploaded_file_id, _, (json_records, warnings) = save_uploaded_file(request, process_records=process_records)
    except ValueError as e:
        return create_json_response({'errors': [str(e)], 'warnings': []}, status=400, reason=str(e))

    response = {
        'uploadedFileId': uploaded_file_id,
        'errors': [],
        'warnings': warnings,
        'info': ['{} individuals will be updated'.format(len(json_records))],
    }
    return create_json_response(response)


def _process_hpo_records(records, filename, project, user):
    if filename.endswith('.json'):
        row_dicts = [_parse_phenotips_record(record) for record in records]
    else:
        column_map = {}
        for i, field in enumerate(records[0]):
            key = field.lower()
            if re.match("hpo.*present", key):
                column_map[FEATURES_COL] = i
            elif re.match("hpo.*absent", key):
                column_map[ABSENT_FEATURES_COL] = i
            elif re.match("hp.*number*", key):
                if not HPO_TERM_NUMBER_COL in column_map:
                    column_map[HPO_TERM_NUMBER_COL] = []
                column_map[HPO_TERM_NUMBER_COL].append(i)
            elif 'family' in key or 'pedigree' in key:
                column_map[FAMILY_ID_COL] = i
            else:
                col_key = next((col for col, text in [
                    (NOTES_COL, 'notes'), (INDIVIDUAL_ID_COL, 'individual'), (AFFECTED_REL_COL, 'affected relative'),
                    (AFFECTED_FEATURE_COL, 'affected'), (BIRTH_COL, 'birth'), (DEATH_COL, 'death'),
                    (ONSET_AGE_COL, 'onset'),  (AR_ICSI_COL, 'relative'),
                    (CONSANGUINITY_COL, 'consanguinity'), (EXP_INHERITANCE_COL, 'inheritance'), (AR_FM_COL, 'fertility'),
                    (AR_IUI_COL, 'intrauterine'), (AR_IVF_COL, 'in vitro'), (AR_ICSI_COL, 'cytoplasmic'),
                    (AR_SURROGACY_COL, 'surrogacy'), (AR_DEGG_COL, 'donor egg'), (AR_DSPERM_COL, 'donor sperm'),
                    (MAT_ETHNICITY_COL, 'maternal ancestry'), (PAT_ETHNICITY_COL, 'paternal ancestry'),
                    (DISORDERS_COL, 'disorders'), (REJECTED_GENES_COL, 'tested genes'),
                    (CANDIDATE_GENES_COL, 'candidate genes'), (ASSIGNED_ANALYST_COL, 'assigned analyst'),
                ] if text in key), None)
                if col_key:
                    column_map[col_key] = i

        if INDIVIDUAL_ID_COL not in column_map:
            raise ValueError('Invalid header, missing individual id column')

        row_dicts = [{column: row[index] if isinstance(index, int) else next((row[i] for i in index if row[i]), None)
                      for column, index in column_map.items()} for row in records[1:]]

        if FEATURES_COL in column_map or ABSENT_FEATURES_COL in column_map:
            for row in row_dicts:
                row[FEATURES_COL] = _parse_hpo_terms(row.get(FEATURES_COL))
                row[ABSENT_FEATURES_COL] = _parse_hpo_terms(row.get(ABSENT_FEATURES_COL))

        elif HPO_TERM_NUMBER_COL in column_map:
            aggregate_rows = defaultdict(lambda: {FEATURES_COL: [], ABSENT_FEATURES_COL: []})
            for row in row_dicts:
                column = ABSENT_FEATURES_COL if row.pop(AFFECTED_FEATURE_COL) == 'no' else FEATURES_COL
                aggregate_entry = aggregate_rows[(row.get(FAMILY_ID_COL), row.get(INDIVIDUAL_ID_COL))]
                term = row.pop(HPO_TERM_NUMBER_COL, None)
                if term:
                    aggregate_entry[column].append(term.strip())
                else:
                    aggregate_entry[column] = []
                aggregate_entry.update({k: v for k, v in row.items() if v})

            return _parse_individual_hpo_terms(list(aggregate_rows.values()), project, user)

    return _parse_individual_hpo_terms(row_dicts, project, user)


def _parse_hpo_terms(hpo_term_string):
    if not hpo_term_string:
        return []
    return [hpo_term.strip() for hpo_term in re.sub(r'\(.*?\)', '', hpo_term_string).replace(',', ';').split(';')]


def _has_same_features(individual, present_features, absent_features):
    return {feature['id'] for feature in individual.features or []} == set(present_features or []) and \
           {feature['id'] for feature in individual.absent_features or []} == set(absent_features or [])


def _parse_individual_hpo_terms(json_records, project, user):
    all_hpo_terms = set()
    for record in json_records:
        all_hpo_terms.update(record.get(FEATURES_COL, []))
        all_hpo_terms.update(record.get(ABSENT_FEATURES_COL, []))
    hpo_terms = set(HumanPhenotypeOntology.objects.filter(hpo_id__in=all_hpo_terms).values_list('hpo_id', flat=True))

    individual_ids = [record[INDIVIDUAL_ID_COL] for record in json_records]
    individual_ids += ['{}_{}'.format(record[FAMILY_ID_COL], record[INDIVIDUAL_ID_COL])
                       for record in json_records if FAMILY_ID_COL in record]
    individual_lookup = defaultdict(dict)
    for i in Individual.objects.filter(family__project=project, individual_id__in=individual_ids).prefetch_related('family'):
        individual_lookup[i.individual_id][i.family.family_id] = i

    allowed_assigned_analysts = None
    if any(record.get(ASSIGNED_ANALYST_COL) for record in json_records):
        allowed_assigned_analysts = {
            u['email'] for u in get_project_collaborators_by_username(
                user, project, fields=['email'], expand_user_groups=True,
            ).values()
        }

    parsed_records = []
    missing_individuals = []
    unchanged_individuals = []
    invalid_hpo_term_individuals = defaultdict(list)
    invalid_values = defaultdict(lambda: defaultdict(list))
    for record in json_records:
        individual, individual_id = _get_record_individual(record, individual_lookup)
        if not individual:
            missing_individuals.append(individual_id)
            continue

        invalid_record_terms = _remove_invalid_hpo_terms(record, hpo_terms)
        for term in invalid_record_terms:
            invalid_hpo_term_individuals[term].append(individual_id)

        update_record = _get_record_updates(record, individual, invalid_values, allowed_assigned_analysts)
        if update_record:
            update_record.update({
                INDIVIDUAL_GUID_COL: individual.guid,
            })
            parsed_records.append(update_record)
        else:
            unchanged_individuals.append(individual_id)

    errors = []
    if not parsed_records:
        errors.append('Unable to find individuals to update for any of the {total} parsed individuals.{missing}{unchanged}'.format(
            total=len(missing_individuals) + len(unchanged_individuals),
            missing=' No matching ids found for {} individuals.'.format(len(missing_individuals)) if missing_individuals else '',
            unchanged=' No changes detected for {} individuals.'.format(len(unchanged_individuals)) if unchanged_individuals else '',
        ))

    warnings = _get_metadata_warnings(invalid_hpo_term_individuals, invalid_values, missing_individuals, unchanged_individuals)

    return parsed_records, errors, warnings


def _get_record_individual(record, individual_lookup):
    family_id = record.pop(FAMILY_ID_COL, None)
    individual_id = record.pop(INDIVIDUAL_ID_COL)
    individuals = individual_lookup[individual_id]
    if family_id:
        individual = individuals.get(family_id)
        if not individual:
            individual = individual_lookup['{}_{}'.format(family_id, individual_id)].get(family_id)
    else:
        individual = next((i for i in individuals.values()), None)
    return individual, individual_id


def _remove_invalid_hpo_terms(record, hpo_terms):
    invalid_terms = set()
    for feature in record.get(FEATURES_COL, []):
        if feature not in hpo_terms:
            invalid_terms.add(feature)
            record[FEATURES_COL].remove(feature)
    for feature in record.get(ABSENT_FEATURES_COL, []):
        if feature not in hpo_terms:
            invalid_terms.add(feature)
            record[ABSENT_FEATURES_COL].remove(feature)
    return invalid_terms


def _get_record_updates(record, individual, invalid_values, allowed_assigned_analysts):
    has_feature_columns = bool(record.get(FEATURES_COL) or record.get(ABSENT_FEATURES_COL))
    has_same_features = has_feature_columns and _has_same_features(individual, record.get(FEATURES_COL),
                                                                   record.get(ABSENT_FEATURES_COL))
    update_record = {}
    for k, v in record.items():
        if not v:
            continue
        try:
            if k == ASSIGNED_ANALYST_COL:
                if v not in allowed_assigned_analysts:
                    raise ValueError
                if v:
                    update_record[k] = v
            else:
                _parsed_val = INDIVIDUAL_METADATA_FIELDS[k](v)
                if (
                    # different features
                    (k in {FEATURES_COL, ABSENT_FEATURES_COL} and not has_same_features)
                    # different value (for non-feature col)
                    or _parsed_val != getattr(individual, k)
                ):
                    update_record[k] = _parsed_val

        except (KeyError, ValueError):
            invalid_values[k][v].append(individual.individual_id)
    return update_record


def _get_metadata_warnings(invalid_hpo_term_individuals, invalid_values, missing_individuals, unchanged_individuals):
    warnings = []
    if invalid_hpo_term_individuals:
        warnings.append(
            "The following HPO terms were not found in seqr's HPO data and will not be added: {}".format(
                '; '.join(['{} ({})'.format(term, ', '.join(individuals))
                           for term, individuals in sorted(invalid_hpo_term_individuals.items())])
            )
        )
    if invalid_values:
        warnings += ['The following invalid values for "{}" will not be added: {}'.format(field, '; '.join([
            '{} ({})'.format(val, ', '.join(individuals)) for val, individuals in errs.items()
        ])) for field, errs in invalid_values.items()]
    if missing_individuals:
        warnings.append(
            'Unable to find matching ids for {} individuals. The following entries will not be updated: {}'.format(
                len(missing_individuals), ', '.join(missing_individuals)
            ))
    if unchanged_individuals:
        warnings.append(
            'No changes detected for {} individuals. The following entries will not be updated: {}'.format(
                len(unchanged_individuals), ', '.join(sorted(unchanged_individuals))
            ))
    return warnings


@login_and_policies_required
def save_individuals_metadata_table_handler(request, project_guid, upload_file_id):
    """
    Handler for 'save' requests to apply HPO terms tables previously uploaded through receive_individuals_metadata_handler
    """
    project = get_project_and_check_permissions(project_guid, request.user)

    json_records, _ = load_uploaded_file(upload_file_id)

    individual_guids = [record[INDIVIDUAL_GUID_COL] for record in json_records]
    individuals = Individual.objects.filter(family__project=project, guid__in=individual_guids)
    individuals_by_guid = {i.guid: i for i in individuals}

    if any(ASSIGNED_ANALYST_COL in record for record in json_records):
        prefetch_related_objects(individuals, 'family')
    family_assigned_analysts = defaultdict(list)

    for record in json_records:
        individual = individuals_by_guid[record[INDIVIDUAL_GUID_COL]]
        update_model_from_json(
            individual, {k: record[k] for k in INDIVIDUAL_METADATA_FIELDS.keys() if k in record}, user=request.user)
        if record.get(ASSIGNED_ANALYST_COL):
            family_assigned_analysts[record[ASSIGNED_ANALYST_COL]].append(individual.family.id)

    response = {
        'individualsByGuid': {
            individual['individualGuid']: individual for individual in _get_json_for_individuals(
            individuals, user=request.user, add_hpo_details=True, project_guid=project_guid,
        )},
    }

    if family_assigned_analysts:
        updated_families = set()
        for user in User.objects.filter(email__in=family_assigned_analysts.keys()):
            updated = Family.bulk_update(request.user, {'assigned_analyst': user}, id__in=family_assigned_analysts[user.email])
            updated_families.update(updated)

        response['familiesByGuid'] = {
            family['familyGuid']: family for family in _get_json_for_families(
            Family.objects.filter(guid__in=updated_families), request.user, project_guid=project_guid, has_case_review_perm=False,
        )}

    return create_json_response(response)


@login_and_policies_required
def get_individual_rna_seq_data(request, individual_guid):
    individual = Individual.objects.get(guid=individual_guid)
    check_project_permissions(individual.family.project, request.user)

    filters = {'sample__individual': individual}
    outlier_data = get_json_for_rna_seq_outliers(filters, significant_only=False, individual_guid=individual_guid)

    genes_to_show = get_genes({
        gene_id for rna_data in outlier_data.get(individual_guid, {}).values() for gene_id, data in rna_data.items()
        if any([d['isSignificant'] for d in (data if isinstance(data, list) else [data])])
    })

    return create_json_response({
        'rnaSeqData': outlier_data,
        'genesById': genes_to_show,
    })


@login_and_policies_required
def get_hpo_terms(request, hpo_parent_id):
    """
    Get all the HPO Terms with the given parent ID
    """

    return create_json_response({
        hpo_parent_id: {
            hpo.hpo_id: {'id': hpo.hpo_id, 'category': hpo.category_id, 'label': hpo.name}
            for hpo in HumanPhenotypeOntology.objects.filter(parent_id=hpo_parent_id)
        }
    })
