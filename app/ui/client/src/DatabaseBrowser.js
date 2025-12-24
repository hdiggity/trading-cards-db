import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import './DatabaseBrowser.css';

// Utility helpers for display normalization
const normalizeCondition = (val) => (val ? String(val).replace(/_/g, ' ').trim().toLowerCase() : '');

// Utility function to format field values for display
const formatFieldValue = (fieldName, value) => {
  // Price estimate: return empty string for null/empty, not N/A
  if (fieldName === 'value_estimate') {
    if (value === null || value === undefined || value === '' || value === 'n/a') return '';
    return String(value).trim();
  }

  if (value === null || value === undefined) return 'N/A';

  const raw = typeof value === 'string' ? value : String(value);
  const noUnderscore = raw.replace(/_/g, ' ').trim();

  switch (fieldName) {
    case 'is_player':
      return value ? 'yes' : 'no';
    case 'features':
      return !noUnderscore || noUnderscore.toLowerCase() === 'none'
        ? 'none'
        : noUnderscore.split(',').map((f) => f.trim().replace(/_/g, ' ').toLowerCase()).join(', ');
    // last_price removed
    case 'date_added':
    case 'last_updated':
      return value ? new Date(value).toLocaleDateString() : 'N/A';
    case 'sport':
      return noUnderscore.toLowerCase();
    case 'name':
      return noUnderscore.toLowerCase();
    case 'brand':
    case 'team':
      return noUnderscore.toLowerCase();
    case 'card_set':
      return noUnderscore.toLowerCase();
    case 'condition':
      return noUnderscore.toLowerCase();
    default:
      return noUnderscore || 'N/A';
  }
};

function DatabaseBrowser() {
  const navigate = useNavigate();
  const [cards, setCards] = useState([]);
  const [loading, setLoading] = useState(true);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalCards, setTotalCards] = useState(0);
  const [searchTerm, setSearchTerm] = useState('');
  const [filterSport, setFilterSport] = useState('');
  const [filterBrand, setFilterBrand] = useState('');
  const [filterCondition, setFilterCondition] = useState('');
  const [filterTeam, setFilterTeam] = useState('');
  const [filterYear, setFilterYear] = useState('');
  const [filterSet, setFilterSet] = useState('');
  const [filterName, setFilterName] = useState('');
  const [filterNumber, setFilterNumber] = useState('');
  const [filterFeatures, setFilterFeatures] = useState('');
  const [filterIsPlayer, setFilterIsPlayer] = useState('');
  const [editingCard, setEditingCard] = useState(null);
  const [editFormData, setEditFormData] = useState({});
  const [fieldOptions, setFieldOptions] = useState({ sports: [], brands: [], conditions: [], teams: [], years: [], card_sets: [] });
  const [selectedCards, setSelectedCards] = useState(new Set());
  const [selectAll, setSelectAll] = useState(false);
  const [sortBy, setSortBy] = useState('');
  const [sortDir, setSortDir] = useState('asc');
  const [modalCard, setModalCard] = useState(null);
  const [modalLoading, setModalLoading] = useState(false);
  const [modalEditMode, setModalEditMode] = useState(false);
  const [modalFormData, setModalFormData] = useState({});
  const [modalIndividualCards, setModalIndividualCards] = useState([]);
  const [editingCopyId, setEditingCopyId] = useState(null);
  const [copyFormData, setCopyFormData] = useState({});
  const [refreshingPrices, setRefreshingPrices] = useState(false);
  const [refreshResult, setRefreshResult] = useState(null);
  const scrollPositionRef = useRef(0);

  useEffect(() => {
    // Save scroll position before fetching
    scrollPositionRef.current = window.pageYOffset || document.documentElement.scrollTop;
    fetchCards();
  }, [currentPage, searchTerm, filterSport, filterBrand, filterCondition, filterTeam, filterYear, filterSet, filterName, filterNumber, filterFeatures, filterIsPlayer, sortBy, sortDir]);

  // Clear selections when page changes or filters change
  useEffect(() => {
    setSelectedCards(new Set());
    setSelectAll(false);
  }, [currentPage, searchTerm, filterSport, filterBrand, filterCondition, filterTeam, filterYear, filterSet, filterName, filterNumber, filterFeatures, filterIsPlayer]);

  // Fetch distinct options for dropdowns
  useEffect(() => {
    (async () => {
      try {
        const r = await fetch('http://localhost:3001/api/field-options');
        const data = await r.json();
        setFieldOptions({
          sports: (data.sports || []).map((s) => String(s).toLowerCase()),
          brands: (data.brands || []).map((s) => String(s).toLowerCase()),
          conditions: (data.conditions || []).map((s) => String(s).toLowerCase()),
          teams: (data.teams || []).map((s) => String(s).toLowerCase()).sort(),
          years: (data.years || []).sort((a, b) => b - a),
          card_sets: (data.card_sets || []).map((s) => String(s).toLowerCase()).sort(),
        });
      } catch (e) {
        setFieldOptions({ sports: [], brands: [], conditions: [], teams: [], years: [], card_sets: [] });
      }
    })();
  }, []);

  const fetchCards = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: currentPage.toString(),
        limit: '20',
        ...(searchTerm && { search: searchTerm }),
        ...(filterSport && { sport: filterSport }),
        ...(filterBrand && { brand: filterBrand }),
        ...(filterCondition && { condition: filterCondition }),
        ...(filterTeam && { team: filterTeam }),
        ...(filterYear && { year: filterYear }),
        ...(filterSet && { card_set: filterSet }),
        ...(filterName && { name: filterName }),
        ...(filterNumber && { number: filterNumber }),
        ...(filterFeatures && { features: filterFeatures }),
        ...(filterIsPlayer && { is_player: filterIsPlayer }),
        ...(sortBy && { sortBy }),
        ...(sortBy && { sortDir })
      });

      const response = await fetch(`http://localhost:3001/api/cards?${params}`);
      const data = await response.json();

      setCards(data.cards || []);
      setTotalPages(data.pagination?.pages || 1);
      setTotalCards(data.pagination?.totalQuantity || data.pagination?.total || 0);
    } catch (error) {
      console.error('Error fetching cards:', error);
    }
    setLoading(false);

    // Restore scroll position after render
    requestAnimationFrame(() => {
      window.scrollTo(0, scrollPositionRef.current);
    });
  };

  const handleSearch = (e) => {
    e.preventDefault();
    setCurrentPage(1);
    fetchCards();
  };

  const handleRefreshPrices = async () => {
    setRefreshingPrices(true);
    setRefreshResult('Refreshing ALL card prices...');

    try {
      const response = await fetch('http://localhost:3001/api/refresh-prices', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batchSize: 25, forceAll: true })
      });
      const result = await response.json();

      if (result.success) {
        const batchText = result.batches ? ` in ${result.batches} batches` : '';
        setRefreshResult(`✓ Updated ${result.updated} of ${result.total} cards${batchText}`);

        // Auto-clear after 10 seconds
        setTimeout(() => setRefreshResult(null), 10000);

        // Refresh the displayed cards to show new prices
        try {
          await fetchCards();
        } catch (err) {
          console.error('Error refreshing card display:', err);
        }
      } else {
        setRefreshResult(`✗ Error: ${result.error || 'Failed to refresh prices'}`);
        setTimeout(() => setRefreshResult(null), 10000);
      }
    } catch (error) {
      console.error('Error refreshing prices:', error);
      setRefreshResult(`✗ Error: Failed to refresh prices`);
      setTimeout(() => setRefreshResult(null), 10000);
    } finally {
      setRefreshingPrices(false);
    }
  };

  const handleEdit = (card) => {
    setEditingCard(card.id);
    // Convert text fields to lowercase when editing
    const textFields = ['name', 'sport', 'brand', 'team', 'card_set'];
    const formData = {
      name: card.name || '',
      sport: card.sport || '',
      brand: card.brand || '',
      number: card.number || '',
      copyright_year: card.copyright_year || '',
      team: card.team || '',
      card_set: card.card_set || '',
      condition: normalizeCondition(card.condition || 'near mint'),
      is_player: card.is_player !== undefined ? card.is_player : true,
      features: card.features || '',
      value_estimate: card.value_estimate || '',
      quantity: card.quantity || 1,
      // last_price removed
    };
    
    // Convert text fields to lowercase
    textFields.forEach(field => {
      if (formData[field] && typeof formData[field] === 'string') {
        formData[field] = formData[field].toLowerCase();
      }
    });
    
    setEditFormData(formData);
  };

  const handleSave = async (cardId) => {
    try {
      const response = await fetch(`http://localhost:3001/api/cards/${cardId}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(editFormData)
      });

      if (response.ok) {
        setEditingCard(null);
        setEditFormData({});
        fetchCards();
      } else {
        alert('Error updating card');
      }
    } catch (error) {
      console.error('Error updating card:', error);
      alert('Error updating card');
    }
  };

  const handleDelete = async (cardId) => {
    if (!window.confirm('Are you sure you want to delete this card?')) {
      return;
    }

    try {
      const response = await fetch(`http://localhost:3001/api/cards/${cardId}`, {
        method: 'DELETE'
      });

      if (response.ok) {
        fetchCards();
      } else {
        alert('Error deleting card');
      }
    } catch (error) {
      console.error('Error deleting card:', error);
      alert('Error deleting card');
    }
  };

  const handleCancel = () => {
    setEditingCard(null);
    setEditFormData({});
  };

  const updateFormField = (field, value) => {
    // Convert text fields to lowercase for consistency
    const textFields = ['name', 'sport', 'brand', 'team', 'card_set'];
    const processedValue = textFields.includes(field) && typeof value === 'string' 
      ? value.toLowerCase() 
      : value;
    setEditFormData(prev => ({
      ...prev,
      [field]: field === 'condition' ? normalizeCondition(processedValue) : processedValue
    }));
  };

  // Selection handling functions
  const handleSelectCard = (cardId) => {
    const newSelected = new Set(selectedCards);
    if (newSelected.has(cardId)) {
      newSelected.delete(cardId);
    } else {
      newSelected.add(cardId);
    }
    setSelectedCards(newSelected);
    setSelectAll(newSelected.size === cards.length && cards.length > 0);
  };

  const handleSelectAll = () => {
    if (selectAll) {
      setSelectedCards(new Set());
      setSelectAll(false);
    } else {
      setSelectedCards(new Set(cards.map(card => card.id)));
      setSelectAll(true);
    }
  };

  const handleBulkDelete = async () => {
    if (selectedCards.size === 0) {
      alert('Please select cards to delete');
      return;
    }

    if (!window.confirm(`Are you sure you want to delete ${selectedCards.size} selected card(s)?`)) {
      return;
    }

    try {
      const deletePromises = Array.from(selectedCards).map(cardId =>
        fetch(`http://localhost:3001/api/cards/${cardId}`, {
          method: 'DELETE'
        })
      );

      const results = await Promise.all(deletePromises);
      const failedDeletes = results.filter(result => !result.ok);

      if (failedDeletes.length > 0) {
        alert(`Failed to delete ${failedDeletes.length} card(s). ${results.length - failedDeletes.length} card(s) deleted successfully.`);
      } else {
        alert(`Successfully deleted ${selectedCards.size} card(s)`);
      }

      setSelectedCards(new Set());
      setSelectAll(false);
      fetchCards();
    } catch (error) {
      console.error('Error during bulk delete:', error);
      alert('Error deleting selected cards');
    }
  };

  const handleCardClick = async (card, e) => {
    // Don't open modal if clicking on checkbox, edit button, or delete button
    if (e.target.type === 'checkbox' || e.target.closest('button') || e.target.closest('input') || e.target.closest('select')) {
      return;
    }
    // Don't open modal if already editing this card in-table
    if (editingCard === card.id) {
      return;
    }

    setModalCard(card);
    setModalLoading(true);
    setModalEditMode(false);
    setModalIndividualCards([]);

    try {
      const response = await fetch(`http://localhost:3001/api/card-cropped-back/${card.id}`);
      const data = await response.json();
      if (data.found && data.individualCards) {
        setModalIndividualCards(data.individualCards);
      }
    } catch (error) {
      console.error('Error fetching individual cards:', error);
    }
    setModalLoading(false);
  };

  const closeModal = () => {
    setModalCard(null);
    setModalEditMode(false);
    setModalFormData({});
    setModalIndividualCards([]);
    setEditingCopyId(null);
    setCopyFormData({});
  };

  const startCopyEdit = (copy) => {
    setEditingCopyId(copy.id);
    setCopyFormData({
      condition: normalizeCondition(copy.condition || 'near mint'),
      value_estimate: copy.value_estimate || '',
      features: copy.features || '',
      notes: copy.notes || ''
    });
  };

  const cancelCopyEdit = () => {
    setEditingCopyId(null);
    setCopyFormData({});
  };

  const saveCopyEdit = async (copyId) => {
    try {
      const response = await fetch(`http://localhost:3001/api/individual-card/${copyId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(copyFormData)
      });

      if (response.ok) {
        // Update the local state
        setModalIndividualCards(prev => prev.map(ic =>
          ic.id === copyId ? { ...ic, ...copyFormData } : ic
        ));
        setEditingCopyId(null);
        setCopyFormData({});
      } else {
        alert('Error updating individual copy');
      }
    } catch (error) {
      console.error('Error updating individual copy:', error);
      alert('Error updating individual copy');
    }
  };

  const updateCopyField = (field, value) => {
    setCopyFormData(prev => ({
      ...prev,
      [field]: field === 'condition' ? normalizeCondition(value) : value
    }));
  };

  const deleteCopy = async (copyId) => {
    if (!window.confirm('Are you sure you want to delete this individual copy?')) {
      return;
    }
    try {
      const response = await fetch(`http://localhost:3001/api/individual-card/${copyId}`, {
        method: 'DELETE'
      });
      const result = await response.json();

      if (result.success) {
        if (result.cardDeleted) {
          // Main card was deleted too, close modal and refresh
          closeModal();
          fetchCards();
        } else {
          // Update local state
          setModalIndividualCards(prev => prev.filter(ic => ic.id !== copyId));
          // Update the modal card quantity
          setModalCard(prev => ({ ...prev, quantity: result.newQuantity }));
          fetchCards();
        }
      } else {
        alert('Error deleting copy: ' + (result.error || 'Unknown error'));
      }
    } catch (error) {
      console.error('Error deleting copy:', error);
      alert('Error deleting copy');
    }
  };

  const startModalEdit = () => {
    const card = modalCard;
    const textFields = ['name', 'sport', 'brand', 'team', 'card_set'];
    const formData = {
      name: card.name || '',
      sport: card.sport || '',
      brand: card.brand || '',
      number: card.number || '',
      copyright_year: card.copyright_year || '',
      team: card.team || '',
      card_set: card.card_set || '',
      condition: normalizeCondition(card.condition || 'near mint'),
      is_player: card.is_player !== undefined ? card.is_player : true,
      features: card.features || '',
      value_estimate: card.value_estimate || '',
      quantity: card.quantity || 1,
    };
    textFields.forEach(field => {
      if (formData[field] && typeof formData[field] === 'string') {
        formData[field] = formData[field].toLowerCase();
      }
    });
    setModalFormData(formData);
    setModalEditMode(true);
  };

  const updateModalField = (field, value) => {
    const textFields = ['name', 'sport', 'brand', 'team', 'card_set'];
    const processedValue = textFields.includes(field) && typeof value === 'string'
      ? value.toLowerCase()
      : value;
    setModalFormData(prev => ({
      ...prev,
      [field]: field === 'condition' ? normalizeCondition(processedValue) : processedValue
    }));
  };

  const saveModalEdit = async () => {
    try {
      const response = await fetch(`http://localhost:3001/api/cards/${modalCard.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(modalFormData)
      });

      if (response.ok) {
        setModalEditMode(false);
        setModalCard({ ...modalCard, ...modalFormData });
        fetchCards();
      } else {
        alert('Error updating card');
      }
    } catch (error) {
      console.error('Error updating card:', error);
      alert('Error updating card');
    }
  };

  const deleteFromModal = async () => {
    if (!window.confirm('Are you sure you want to delete this card?')) {
      return;
    }
    try {
      const response = await fetch(`http://localhost:3001/api/cards/${modalCard.id}`, {
        method: 'DELETE'
      });
      if (response.ok) {
        closeModal();
        fetchCards();
      } else {
        alert('Error deleting card');
      }
    } catch (error) {
      console.error('Error deleting card:', error);
      alert('Error deleting card');
    }
  };

  return (
    <div className="database-browser">
      <header className="browser-header">
        <div className="header-top">
          <h1>DATABASE BROWSER</h1>
          <div className="header-buttons">
            {selectedCards.size > 0 && (
              <button
                className="bulk-delete-button"
                onClick={handleBulkDelete}
              >
                DELETE SELECTED ({selectedCards.size})
              </button>
            )}
            <button
              className="back-button"
              onClick={() => navigate('/')}
            >
              ← BACK TO MAIN
            </button>
          </div>
        </div>

        <div className="search-filters">
          <div className="total-count">
            TOTAL CARDS: {totalCards}
          </div>

          <form onSubmit={handleSearch} className="search-form">
            <input
              type="text"
              placeholder="SEARCH BY NAME, TEAM, OR SET..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="search-input"
            />
            <button type="submit" className="search-button">SEARCH</button>
          </form>

          <div className="filters">
            <input
              list="sports-list"
              value={filterSport}
              onChange={(e) => setFilterSport(e.target.value)}
              placeholder="sport"
              className="filter-select"
            />
            <datalist id="sports-list">
              {fieldOptions.sports.map((s) => (
                <option key={s} value={s} />
              ))}
            </datalist>

            <input
              list="brands-list"
              value={filterBrand}
              onChange={(e) => setFilterBrand(e.target.value)}
              placeholder="brand"
              className="filter-select"
            />
            <datalist id="brands-list">
              {fieldOptions.brands.map((b) => (
                <option key={b} value={b} />
              ))}
            </datalist>

            <input
              list="years-list"
              value={filterYear}
              onChange={(e) => setFilterYear(e.target.value)}
              placeholder="year"
              className="filter-select"
            />
            <datalist id="years-list">
              {fieldOptions.years.map((y) => (
                <option key={y} value={y} />
              ))}
            </datalist>

            <input
              list="teams-list"
              value={filterTeam}
              onChange={(e) => setFilterTeam(e.target.value)}
              placeholder="team"
              className="filter-select"
            />
            <datalist id="teams-list">
              {fieldOptions.teams.map((t) => (
                <option key={t} value={t} />
              ))}
            </datalist>

            <input
              list="sets-list"
              value={filterSet}
              onChange={(e) => setFilterSet(e.target.value)}
              placeholder="set"
              className="filter-select"
            />
            <datalist id="sets-list">
              {fieldOptions.card_sets.map((cs) => (
                <option key={cs} value={cs} />
              ))}
            </datalist>

            <input
              list="conditions-list"
              value={filterCondition}
              onChange={(e) => setFilterCondition(e.target.value)}
              placeholder="condition"
              className="filter-select"
            />
            <datalist id="conditions-list">
              {fieldOptions.conditions.map((c) => (
                <option key={c} value={c} />
              ))}
            </datalist>

            <input
              type="text"
              value={filterName}
              onChange={(e) => setFilterName(e.target.value)}
              placeholder="name"
              className="filter-select"
            />

            <input
              type="text"
              value={filterNumber}
              onChange={(e) => setFilterNumber(e.target.value)}
              placeholder="number"
              className="filter-select"
            />

            <input
              type="text"
              value={filterFeatures}
              onChange={(e) => setFilterFeatures(e.target.value)}
              placeholder="features"
              className="filter-select"
            />

            <select
              value={filterIsPlayer}
              onChange={(e) => setFilterIsPlayer(e.target.value)}
              className="filter-select"
            >
              <option value="">cards</option>
              <option value="true">player cards</option>
              <option value="false">non-player cards</option>
            </select>

            <button
              className="refresh-prices-button"
              onClick={handleRefreshPrices}
              disabled={refreshingPrices}
              title="Refresh price estimates using AI (token-efficient batching)"
            >
              {refreshingPrices ? 'REFRESHING...' : 'REFRESH PRICES'}
            </button>

            <button
              className="reset-filters-button"
              onClick={() => {
                setFilterSport('');
                setFilterBrand('');
                setFilterCondition('');
                setFilterTeam('');
                setFilterYear('');
                setFilterSet('');
                setFilterName('');
                setFilterNumber('');
                setFilterFeatures('');
                setFilterIsPlayer('');
                setSearchTerm('');
                setSortBy('');
                setSortDir('asc');
                setCurrentPage(1);
              }}
              title="Reset all filters and search"
            >
              RESET FILTERS
            </button>

            {refreshResult && (
              <span className="refresh-result">{refreshResult}</span>
            )}
          </div>
        </div>
      </header>

      {loading ? (
        <div className="loading">Loading cards...</div>
      ) : (
        <>
          <div className="cards-table">
            <table>
              <thead>
                <tr>
                  <th>
                    <input
                      type="checkbox"
                      checked={selectAll}
                      onChange={handleSelectAll}
                      title="Select All"
                    />
                  </th>
                  {[
                    ['name','NAME'],
                    ['sport','SPORT'],
                    ['brand','BRAND'],
                    ['number','NUMBER'],
                    ['copyright_year','YEAR'],
                    ['team','TEAM'],
                    ['card_set','SET'],
                    ['condition','CONDITION'],
                    ['is_player','PLAYER CARD'],
                    ['features','FEATURES'],
                    ['value_estimate','PRICE ESTIMATE'],
                    ['quantity','QTY'],
                    ['date_added','DATE ADDED'],
                  ].map(([key,label]) => (
                    <th
                      key={key}
                      className={`sortable ${sortBy===key ? 'sorted' : ''}`}
                      onClick={(e) => {
                        e.preventDefault();
                        if (sortBy === key) setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
                        else { setSortBy(key); setSortDir('asc'); }
                        setCurrentPage(1);
                      }}
                      title={`Sort by ${label}${sortBy===key ? (sortDir==='asc'?' (asc)':' (desc)') : ''}`}
                    >
                      {label}{sortBy===key ? (sortDir==='asc' ? ' ▲' : ' ▼') : ''}
                    </th>
                  ))}
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {cards.map((card) => (
                  <tr key={card.id} onClick={(e) => handleCardClick(card, e)} className="clickable-row">
                    {editingCard === card.id ? (
                      <>
                        <td>
                          <input
                            type="checkbox"
                            checked={selectedCards.has(card.id)}
                            onChange={() => handleSelectCard(card.id)}
                          />
                        </td>
                        <td><input type="text" value={editFormData.name} onChange={(e) => updateFormField('name', e.target.value)} /></td>
                        <td><input type="text" value={editFormData.sport} onChange={(e) => updateFormField('sport', e.target.value)} /></td>
                        <td><input type="text" value={editFormData.brand} onChange={(e) => updateFormField('brand', e.target.value)} /></td>
                        <td><input type="text" value={editFormData.number} onChange={(e) => updateFormField('number', e.target.value)} /></td>
                        <td><input type="text" value={editFormData.copyright_year} onChange={(e) => updateFormField('copyright_year', e.target.value)} /></td>
                        <td><input type="text" value={editFormData.team} onChange={(e) => updateFormField('team', e.target.value)} /></td>
                        <td><input type="text" value={editFormData.card_set} onChange={(e) => updateFormField('card_set', e.target.value)} /></td>
                        <td>
                          <select value={normalizeCondition(editFormData.condition)} onChange={(e) => updateFormField('condition', e.target.value)}>
                            <option value="gem mint">gem mint (10)</option>
                            <option value="mint">mint (9)</option>
                            <option value="near mint">near mint (8)</option>
                            <option value="excellent">excellent (7)</option>
                            <option value="very good">very good (6)</option>
                            <option value="good">good (5)</option>
                            <option value="fair">fair (4)</option>
                            <option value="poor">poor (3)</option>
                          </select>
                        </td>
                        <td>
                          <select value={editFormData.is_player} onChange={(e) => updateFormField('is_player', e.target.value === 'true')}>
                            <option value={true}>Yes</option>
                            <option value={false}>No</option>
                          </select>
                        </td>
                        <td><input type="text" value={editFormData.features || ''} onChange={(e) => updateFormField('features', e.target.value)} placeholder="e.g., rookie, autograph" /></td>
                        <td><input type="text" value={editFormData.value_estimate || ''} onChange={(e) => updateFormField('value_estimate', e.target.value)} placeholder="$1-5 or $12.34" /></td>
                        <td><input type="number" value={editFormData.quantity} onChange={(e) => updateFormField('quantity', parseInt(e.target.value))} /></td>
                        <td><span className="readonly-field">{formatFieldValue('date_added', card.date_added)}</span></td>
                        <td className="actions">
                          <button onClick={() => handleSave(card.id)} className="save-btn">SAVE</button>
                          <button onClick={handleCancel} className="cancel-btn">CANCEL</button>
                        </td>
                      </>
                    ) : (
                      <>
                        <td>
                          <input
                            type="checkbox"
                            checked={selectedCards.has(card.id)}
                            onChange={() => handleSelectCard(card.id)}
                          />
                        </td>
                        <td className={`${sortBy==='name'?'sorted-cell':''}`}>{formatFieldValue('name', card.name)}</td>
                        <td className={`${sortBy==='sport'?'sorted-cell':''} clickable-cell`} onClick={() => card.sport && setFilterSport(card.sport)}>{formatFieldValue('sport', card.sport)}</td>
                        <td className={`${sortBy==='brand'?'sorted-cell':''} clickable-cell`} onClick={() => card.brand && setFilterBrand(card.brand)}>{formatFieldValue('brand', card.brand)}</td>
                        <td className={`${sortBy==='number'?'sorted-cell':''}`}>{formatFieldValue('number', card.number)}</td>
                        <td className={`${sortBy==='copyright_year'?'sorted-cell':''} clickable-cell`} onClick={() => card.copyright_year && setFilterYear(card.copyright_year)}>{formatFieldValue('copyright_year', card.copyright_year)}</td>
                        <td className={`${sortBy==='team'?'sorted-cell':''} clickable-cell`} onClick={() => card.team && setFilterTeam(card.team)}>{formatFieldValue('team', card.team)}</td>
                        <td className={`${sortBy==='card_set'?'sorted-cell':''} clickable-cell`} onClick={() => card.card_set && setFilterSet(card.card_set)}>{formatFieldValue('card_set', card.card_set)}</td>
                        <td className={`${sortBy==='condition'?'sorted-cell':''} clickable-cell`} onClick={() => card.condition && setFilterCondition(card.condition)}>{card.quantity > 1 ? 'multiple' : formatFieldValue('condition', card.condition)}</td>
                        <td className={`${sortBy==='is_player'?'sorted-cell':''}`}>{formatFieldValue('is_player', card.is_player)}</td>
                        <td className={`${sortBy==='features'?'sorted-cell':''}`}>{card.quantity > 1 ? 'multiple' : formatFieldValue('features', card.features)}</td>
                        <td className={`${sortBy==='value_estimate'?'sorted-cell':''}`}>{card.quantity > 1 ? 'multiple' : formatFieldValue('value_estimate', card.value_estimate)}</td>
                        <td className={`${sortBy==='quantity'?'sorted-cell':''}`}>{formatFieldValue('quantity', card.quantity)}</td>
                        <td className={`${sortBy==='date_added'?'sorted-cell':''}`}>{card.quantity > 1 ? 'multiple' : formatFieldValue('date_added', card.date_added)}</td>
                        <td className="actions">
                          <button onClick={() => handleEdit(card)} className="edit-btn">EDIT</button>
                          <button onClick={() => handleDelete(card.id)} className="delete-btn">DELETE</button>
                        </td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="pagination">
            <button
              onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
              disabled={currentPage === 1}
              className="page-btn"
            >
              PREVIOUS
            </button>
            <span className="page-info">
              PAGE {currentPage} OF {totalPages}
            </span>
            <button
              onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
              disabled={currentPage === totalPages}
              className="page-btn"
            >
              NEXT
            </button>
          </div>
        </>
      )}

      {modalCard && (
        <div className="card-modal-overlay" onClick={closeModal}>
          <div className="card-modal" onClick={(e) => e.stopPropagation()}>
            <button className="modal-close" onClick={closeModal}>x</button>

            <div className="modal-content">
              <div className="modal-details-section">
                <h2>{modalCard.name || 'Unknown Card'}</h2>

                {!modalEditMode ? (
                  <div className="modal-card-details">
                    <div className="detail-row"><span className="detail-label">sport:</span> {formatFieldValue('sport', modalCard.sport)}</div>
                    <div className="detail-row"><span className="detail-label">brand:</span> {formatFieldValue('brand', modalCard.brand)}</div>
                    <div className="detail-row"><span className="detail-label">number:</span> {formatFieldValue('number', modalCard.number)}</div>
                    <div className="detail-row"><span className="detail-label">year:</span> {formatFieldValue('copyright_year', modalCard.copyright_year)}</div>
                    <div className="detail-row"><span className="detail-label">team:</span> {formatFieldValue('team', modalCard.team)}</div>
                    <div className="detail-row"><span className="detail-label">set:</span> {formatFieldValue('card_set', modalCard.card_set)}</div>
                    <div className="detail-row"><span className="detail-label">quantity:</span> {formatFieldValue('quantity', modalCard.quantity)}</div>

                    {modalLoading ? (
                      <div className="modal-loading">loading individual cards...</div>
                    ) : modalIndividualCards.length > 0 ? (
                      <div className="individual-cards-section">
                        <h3>individual copies ({modalIndividualCards.length})</h3>
                        {modalIndividualCards.map((ic, idx) => (
                          <div key={ic.id || idx} className="individual-card-entry">
                            <div className="individual-card-header">
                              copy {idx + 1}
                              {editingCopyId !== ic.id && (
                                <div className="copy-actions">
                                  <button onClick={() => startCopyEdit(ic)} className="edit-copy-btn">EDIT</button>
                                  <button onClick={() => deleteCopy(ic.id)} className="delete-copy-btn">DELETE</button>
                                </div>
                              )}
                            </div>
                            {ic.cropped_back_file && (
                              <div className="individual-card-image">
                                <img
                                  src={`http://localhost:3001/api/cropped-back-image/${encodeURIComponent(ic.cropped_back_file)}`}
                                  alt={`${ic.name || 'card'} back`}
                                  className="cropped-back-thumbnail"
                                  onError={(e) => {
                                    // Try verified directory if pending fails
                                    e.target.src = `http://localhost:3001/api/verified-cropped-back-image/${encodeURIComponent(ic.cropped_back_file)}`;
                                  }}
                                />
                              </div>
                            )}
                            {editingCopyId === ic.id ? (
                              <div className="copy-edit-form">
                                <div className="form-row">
                                  <label>condition:</label>
                                  <select value={copyFormData.condition} onChange={(e) => updateCopyField('condition', e.target.value)}>
                                    <option value="gem mint">gem mint (10)</option>
                                    <option value="mint">mint (9)</option>
                                    <option value="near mint">near mint (8)</option>
                                    <option value="excellent">excellent (7)</option>
                                    <option value="very good">very good (6)</option>
                                    <option value="good">good (5)</option>
                                    <option value="fair">fair (4)</option>
                                    <option value="poor">poor (3)</option>
                                  </select>
                                </div>
                                <div className="form-row">
                                  <label>value:</label>
                                  <input type="text" value={copyFormData.value_estimate} onChange={(e) => updateCopyField('value_estimate', e.target.value)} placeholder="$1-5 or $12.34" />
                                </div>
                                <div className="form-row">
                                  <label>features:</label>
                                  <input type="text" value={copyFormData.features} onChange={(e) => updateCopyField('features', e.target.value)} placeholder="e.g., rookie, autograph" />
                                </div>
                                <div className="form-row">
                                  <label>notes:</label>
                                  <input type="text" value={copyFormData.notes} onChange={(e) => updateCopyField('notes', e.target.value)} />
                                </div>
                                <div className="copy-edit-actions">
                                  <button onClick={() => saveCopyEdit(ic.id)} className="save-btn">SAVE</button>
                                  <button onClick={cancelCopyEdit} className="cancel-btn">CANCEL</button>
                                </div>
                              </div>
                            ) : (
                              <>
                                <div className="detail-row"><span className="detail-label">condition:</span> {formatFieldValue('condition', ic.condition)}</div>
                                <div className="detail-row"><span className="detail-label">value:</span> {formatFieldValue('value_estimate', ic.value_estimate) || 'N/A'}</div>
                                <div className="detail-row"><span className="detail-label">features:</span> {formatFieldValue('features', ic.features)}</div>
                                <div className="detail-row"><span className="detail-label">verified:</span> {ic.verification_date ? new Date(ic.verification_date).toLocaleDateString() : 'N/A'}</div>
                                <div className="detail-row"><span className="detail-label">source file:</span> {ic.source_file || 'N/A'}</div>
                                <div className="detail-row"><span className="detail-label">grid position:</span> {ic.grid_position || 'N/A'}</div>
                                {ic.notes && <div className="detail-row"><span className="detail-label">notes:</span> {ic.notes}</div>}
                              </>
                            )}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="modal-no-image">no individual card records found</div>
                    )}

                    <div className="modal-actions">
                      <button onClick={startModalEdit} className="edit-btn">EDIT</button>
                      <button onClick={deleteFromModal} className="delete-btn">DELETE</button>
                    </div>
                  </div>
                ) : (
                  <div className="modal-edit-form">
                    <div className="form-row">
                      <label>name:</label>
                      <input type="text" value={modalFormData.name} onChange={(e) => updateModalField('name', e.target.value)} />
                    </div>
                    <div className="form-row">
                      <label>sport:</label>
                      <input type="text" value={modalFormData.sport} onChange={(e) => updateModalField('sport', e.target.value)} />
                    </div>
                    <div className="form-row">
                      <label>brand:</label>
                      <input type="text" value={modalFormData.brand} onChange={(e) => updateModalField('brand', e.target.value)} />
                    </div>
                    <div className="form-row">
                      <label>number:</label>
                      <input type="text" value={modalFormData.number} onChange={(e) => updateModalField('number', e.target.value)} />
                    </div>
                    <div className="form-row">
                      <label>year:</label>
                      <input type="text" value={modalFormData.copyright_year} onChange={(e) => updateModalField('copyright_year', e.target.value)} />
                    </div>
                    <div className="form-row">
                      <label>team:</label>
                      <input type="text" value={modalFormData.team} onChange={(e) => updateModalField('team', e.target.value)} />
                    </div>
                    <div className="form-row">
                      <label>set:</label>
                      <input type="text" value={modalFormData.card_set} onChange={(e) => updateModalField('card_set', e.target.value)} />
                    </div>
                    <div className="form-row">
                      <label>condition:</label>
                      <select value={normalizeCondition(modalFormData.condition)} onChange={(e) => updateModalField('condition', e.target.value)}>
                        <option value="gem mint">gem mint (10)</option>
                        <option value="mint">mint (9)</option>
                        <option value="near mint">near mint (8)</option>
                        <option value="excellent">excellent (7)</option>
                        <option value="very good">very good (6)</option>
                        <option value="good">good (5)</option>
                        <option value="fair">fair (4)</option>
                        <option value="poor">poor (3)</option>
                      </select>
                    </div>
                    <div className="form-row">
                      <label>features:</label>
                      <input type="text" value={modalFormData.features || ''} onChange={(e) => updateModalField('features', e.target.value)} placeholder="e.g., rookie, autograph" />
                    </div>
                    <div className="form-row">
                      <label>value:</label>
                      <input type="text" value={modalFormData.value_estimate || ''} onChange={(e) => updateModalField('value_estimate', e.target.value)} placeholder="$1-5 or $12.34" />
                    </div>
                    <div className="form-row">
                      <label>quantity:</label>
                      <input type="number" value={modalFormData.quantity} onChange={(e) => updateModalField('quantity', parseInt(e.target.value))} />
                    </div>

                    <div className="modal-actions">
                      <button onClick={saveModalEdit} className="save-btn">SAVE</button>
                      <button onClick={() => setModalEditMode(false)} className="cancel-btn">CANCEL</button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default DatabaseBrowser;
