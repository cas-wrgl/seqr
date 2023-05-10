import React from 'react'
import PropTypes from 'prop-types'

import { RNASEQ_JUNCTION_PADDING, RNA_SEQ_SPLICE_COLUMNS } from 'shared/utils/constants'
import { GeneSearchLink } from 'shared/components/buttons/SearchResultsLink'
import DataTable from 'shared/components/table/DataTable'
import FamilyReads from 'shared/components/panel/family/FamilyReads'
import { COVERAGE_TYPE, JUNCTION_TYPE } from 'shared/components/panel/family/constants'
import ShowGeneModal from 'shared/components/buttons/ShowGeneModal'
import { ButtonLink } from 'shared/components/StyledComponents'
import { getLocus } from 'shared/components/panel/variants/VariantUtils'

const getJunctionLocus = (junction) => {
  const size = junction.end && junction.end - junction.start
  return getLocus(junction.chrom, junction.start, RNASEQ_JUNCTION_PADDING, size)
}

class BaseRnaSeqJunctionOutliersTable extends React.PureComponent {

  static propTypes = {
    reads: PropTypes.object,
    updateReads: PropTypes.func,
    data: PropTypes.arrayOf(PropTypes.object),
    familyGuid: PropTypes.string,
  }

  openReads = row => () => {
    const { updateReads, familyGuid } = this.props
    updateReads(familyGuid, getJunctionLocus(row), [JUNCTION_TYPE, COVERAGE_TYPE])
  }

  render() {
    const { data, reads, familyGuid } = this.props
    const junctionColumns = [{
      name: 'junctionLocus',
      content: 'Junction',
      width: 4,
      format: row => (
        <div>
          <ButtonLink onClick={this.openReads(row)}>
            {row.junctionLocus}
          </ButtonLink>
          <GeneSearchLink
            buttonText=""
            icon="search"
            location={`${row.chrom}:${Math.max(1, row.start - RNASEQ_JUNCTION_PADDING)}-${row.end + RNASEQ_JUNCTION_PADDING}`}
            familyGuid={familyGuid}
          />
        </div>
      ),
    }, {
      name: 'gene',
      content: 'Gene',
      width: 2,
      format: row => (
        <div>
          <ShowGeneModal gene={row} />
          <GeneSearchLink
            buttonText=""
            icon="search"
            location={row.geneId}
            familyGuid={familyGuid}
            floated="right"
          />
        </div>
      ),
    }].concat(RNA_SEQ_SPLICE_COLUMNS)

    return (
      <div>
        {reads}
        <DataTable
          data={data}
          idField="idField"
          columns={junctionColumns}
          defaultSortColumn="pValue"
          maxHeight="600px"
        />
      </div>
    )
  }

}

const RnaSeqJunctionOutliersTable = props => (
  <FamilyReads layout={BaseRnaSeqJunctionOutliersTable} noTriggerButton {...props} />
)

export default RnaSeqJunctionOutliersTable
