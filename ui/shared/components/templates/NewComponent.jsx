import React from 'react'
//import { Grid } from 'semantic-ui-react'
//import { connect } from 'react-redux'
//import { bindActionCreators } from 'redux'

class NewComponent extends React.Component
{
  static propTypes = {
    //project: React.PropTypes.object.isRequired,
  }

  constructor(props) {
    super(props)

    this.state = {
      //showModal: false,
    }
  }

  render() {
    return null
  }
}

export default NewComponent

/*
const mapStateToProps = state => ({ showCategories: state.projectsTableState.showCategories })

const mapDispatchToProps = dispatch => bindActionCreators({
  onChange: null,
}, dispatch)

export default connect(mapStateToProps, mapDispatchToProps)(NewComponent)
*/
