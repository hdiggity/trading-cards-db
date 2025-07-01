import React, { useState, useEffect } from 'react';
import './DatabaseBrowser.css';

// Utility function to format field names for display
const formatFieldName = (fieldName) => {
  const fieldMap = {
    'name': 'Name',
    'sport': 'Sport',
    'brand': 'Brand',
    'number': 'Number',
    'copyright_year': 'Year',
    'team': 'Team',
    'card_set': 'Set',
    'condition': 'Condition',
    'is_player_card': 'Player Card',
    'features': 'Features',
    'quantity': 'Qty',
    'last_price': 'Last Price',
    'date_added': 'Date Added',
    'last_updated': 'Last Updated'
  };
  return fieldMap[fieldName] || fieldName.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
};

// Utility function to format field values for display
const formatFieldValue = (fieldName, value) => {
  if (value === null || value === undefined) return 'N/A';
  
  switch (fieldName) {
    case 'is_player_card':
      return value ? 'Yes' : 'No';
    case 'features':
      return value === 'none' || !value ? 'None' : value;
    case 'last_price':
      return value ? `$${parseFloat(value).toFixed(2)}` : 'N/A';
    case 'date_added':
    case 'last_updated':
      return value ? new Date(value).toLocaleDateString() : 'N/A';
    default:
      return value || 'N/A';
  }
};

function DatabaseBrowser({ onNavigate }) {
  const [cards, setCards] = useState([]);
  const [loading, setLoading] = useState(true);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [searchTerm, setSearchTerm] = useState('');
  const [filterSport, setFilterSport] = useState('');
  const [filterBrand, setFilterBrand] = useState('');
  const [filterCondition, setFilterCondition] = useState('');
  const [editingCard, setEditingCard] = useState(null);
  const [editFormData, setEditFormData] = useState({});
  const [selectedCards, setSelectedCards] = useState(new Set());
  const [selectAll, setSelectAll] = useState(false);

  useEffect(() => {
    fetchCards();
  }, [currentPage, searchTerm, filterSport, filterBrand, filterCondition]);

  // Clear selections when page changes or filters change
  useEffect(() => {
    setSelectedCards(new Set());
    setSelectAll(false);
  }, [currentPage, searchTerm, filterSport, filterBrand, filterCondition]);

  const fetchCards = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: currentPage.toString(),
        limit: '20',
        ...(searchTerm && { search: searchTerm }),
        ...(filterSport && { sport: filterSport }),
        ...(filterBrand && { brand: filterBrand }),
        ...(filterCondition && { condition: filterCondition })
      });

      const response = await fetch(`http://localhost:3001/api/cards?${params}`);
      const data = await response.json();
      
      setCards(data.cards || []);
      setTotalPages(data.pagination?.pages || 1);
    } catch (error) {
      console.error('Error fetching cards:', error);
    }
    setLoading(false);
  };

  const handleSearch = (e) => {
    e.preventDefault();
    setCurrentPage(1);
    fetchCards();
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
      condition: card.condition || 'near_mint',
      is_player_card: card.is_player_card !== undefined ? card.is_player_card : true,
      features: card.features || '',
      quantity: card.quantity || 1,
      last_price: card.last_price || ''
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
      [field]: processedValue
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

  return (
    <div className="database-browser">
      <header className="browser-header">
        <div className="header-top">
          <h1>Database Browser</h1>
          <div className="header-buttons">
            {selectedCards.size > 0 && (
              <button 
                className="bulk-delete-button" 
                onClick={handleBulkDelete}
              >
                Delete Selected ({selectedCards.size})
              </button>
            )}
            <button 
              className="back-button" 
              onClick={() => onNavigate('main')}
            >
              ← Back to Main
            </button>
          </div>
        </div>
        
        <div className="search-filters">
          <form onSubmit={handleSearch} className="search-form">
            <input
              type="text"
              placeholder="Search by name, team, or set..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="search-input"
            />
            <button type="submit" className="search-button">Search</button>
          </form>
          
          <div className="filters">
            <select 
              value={filterSport} 
              onChange={(e) => setFilterSport(e.target.value)}
              className="filter-select"
            >
              <option value="">All Sports</option>
              <option value="baseball">Baseball</option>
              <option value="basketball">Basketball</option>
              <option value="football">Football</option>
              <option value="hockey">Hockey</option>
            </select>
            
            <select 
              value={filterBrand} 
              onChange={(e) => setFilterBrand(e.target.value)}
              className="filter-select"
            >
              <option value="">All Brands</option>
              <option value="topps">Topps</option>
              <option value="panini">Panini</option>
              <option value="upper deck">Upper Deck</option>
              <option value="bowman">Bowman</option>
            </select>
            
            <select 
              value={filterCondition} 
              onChange={(e) => setFilterCondition(e.target.value)}
              className="filter-select"
            >
              <option value="">All Conditions</option>
              <option value="gem_mint">Gem Mint (10)</option>
              <option value="mint">Mint (9)</option>
              <option value="near_mint">Near Mint (8)</option>
              <option value="excellent">Excellent (7)</option>
              <option value="very_good">Very Good (6)</option>
              <option value="good">Good (5)</option>
              <option value="fair">Fair (4)</option>
              <option value="poor">Poor (3)</option>
            </select>
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
                  <th>Name</th>
                  <th>Sport</th>
                  <th>Brand</th>
                  <th>Number</th>
                  <th>Year</th>
                  <th>Team</th>
                  <th>Set</th>
                  <th>Condition</th>
                  <th>Player Card</th>
                  <th>Features</th>
                  <th>Qty</th>
                  <th>Last Price</th>
                  <th>Date Added</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {cards.map((card) => (
                  <tr key={card.id}>
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
                          <select value={editFormData.condition} onChange={(e) => updateFormField('condition', e.target.value)}>
                            <option value="gem_mint">Gem Mint (10)</option>
                            <option value="mint">Mint (9)</option>
                            <option value="near_mint">Near Mint (8)</option>
                            <option value="excellent">Excellent (7)</option>
                            <option value="very_good">Very Good (6)</option>
                            <option value="good">Good (5)</option>
                            <option value="fair">Fair (4)</option>
                            <option value="poor">Poor (3)</option>
                          </select>
                        </td>
                        <td>
                          <select value={editFormData.is_player_card} onChange={(e) => updateFormField('is_player_card', e.target.value === 'true')}>
                            <option value={true}>Yes</option>
                            <option value={false}>No</option>
                          </select>
                        </td>
                        <td><input type="text" value={editFormData.features || ''} onChange={(e) => updateFormField('features', e.target.value)} placeholder="e.g., rookie, autograph" /></td>
                        <td><input type="number" value={editFormData.quantity} onChange={(e) => updateFormField('quantity', parseInt(e.target.value))} /></td>
                        <td><input type="text" value={editFormData.last_price || ''} onChange={(e) => updateFormField('last_price', e.target.value)} placeholder="0.00" /></td>
                        <td><span className="readonly-field">{formatFieldValue('date_added', card.date_added)}</span></td>
                        <td className="actions">
                          <button onClick={() => handleSave(card.id)} className="save-btn">Save</button>
                          <button onClick={handleCancel} className="cancel-btn">Cancel</button>
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
                        <td>{formatFieldValue('name', card.name)}</td>
                        <td>{formatFieldValue('sport', card.sport)}</td>
                        <td>{formatFieldValue('brand', card.brand)}</td>
                        <td>{formatFieldValue('number', card.number)}</td>
                        <td>{formatFieldValue('copyright_year', card.copyright_year)}</td>
                        <td>{formatFieldValue('team', card.team)}</td>
                        <td>{formatFieldValue('card_set', card.card_set)}</td>
                        <td>{formatFieldValue('condition', card.condition)}</td>
                        <td>{formatFieldValue('is_player_card', card.is_player_card)}</td>
                        <td>{formatFieldValue('features', card.features)}</td>
                        <td>{formatFieldValue('quantity', card.quantity)}</td>
                        <td>{formatFieldValue('last_price', card.last_price)}</td>
                        <td>{formatFieldValue('date_added', card.date_added)}</td>
                        <td className="actions">
                          <button onClick={() => handleEdit(card)} className="edit-btn">Edit</button>
                          <button onClick={() => handleDelete(card.id)} className="delete-btn">Delete</button>
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
              Previous
            </button>
            <span className="page-info">
              Page {currentPage} of {totalPages}
            </span>
            <button 
              onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
              disabled={currentPage === totalPages}
              className="page-btn"
            >
              Next
            </button>
          </div>
        </>
      )}
    </div>
  );
}

export default DatabaseBrowser;