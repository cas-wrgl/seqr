import React from 'react'
import { Divider, Button } from 'semantic-ui-react'

import AwesomeBar from 'shared/components/page/AwesomeBar'
import { Phenotypes } from 'shared/components/panel/MatchmakerPanel'
import DataTable from 'shared/components/table/DataTable'
import { HorizontalSpacer } from 'shared/components/Spacers'
import { HttpRequestHelper } from 'shared/utils/httpRequestHelper'

const SEARCH_CATEGORIES = ['hpo_terms']

const COLUMNS = [
  {
    name: 'familyData',
    content: 'Family',
    width: 4,
    format: JSON.stringify,
    // format: row => (
    //   <Link to={`/project/${row.projectGuid}/family_page/${row.familyGuid}/matchmaker_exchange`} target="_blank">
    //     {row.individualId}
    //   </Link>
    // ),
  },
  { name: 'displayName', content: 'Individual', width: 4 },
  {
    name: 'features',
    content: 'HPO Terms',
    width: 8,
    format: row => <Phenotypes phenotypes={row.features} />,
  },
]

class Hpo extends React.PureComponent {

  static propTypes = {}

  state = {
    data: [],
    terms: [],
    loading: false,
    error: null,
  }

  loadTermData = (result) => {
    this.setState(prevState => ({ loading: true, terms: prevState.terms.concat(result) }))
    new HttpRequestHelper(`/api/summary_data/hpo/${result.key}`,
      (responseJson) => {
        // TODO merge with previous data
        this.setState({ loading: false, data: responseJson.data })
      },
      (e) => {
        this.setState({ loading: false, error: e.message })
      }).get()
  }

  removeTerm = (e, { term }) => {
    // TODO filter removed data
    this.setState(prevState => ({ terms: prevState.terms.filter(({ key }) => key !== term) }))
  }

  render() {
    const { terms, data, loading, error } = this.state
    return (
      <div>
        <AwesomeBar
          categories={SEARCH_CATEGORIES}
          inputwidth="300px"
          placeholder="Search for an HPO term"
          onResultSelect={this.loadTermData}
        />
        <HorizontalSpacer width={10} />
        {terms.map(({ title, description, key }) => (
          <Button
            key={key}
            term={key}
            content={`${title} ${description}`}
            onClick={this.removeTerm}
            size="tiny"
            color="grey"
            icon="delete"
            compact
          />
        ))}
        <Divider />
        <DataTable
          data={data}
          loading={loading}
          idField="individualGuid"
          defaultSortColumn="displayName"
          defaultSortDescending
          fixed
          emptyContent={error || (terms.length ? 'No families with selected terms' : 'Select an HPO term')}
          columns={COLUMNS}
        />
      </div>
    )
  }

}

export default Hpo
