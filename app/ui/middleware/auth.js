const jwt = require('jsonwebtoken');
const path = require('path');
const fs = require('fs');

// load jwt secret from environment
const JWT_SECRET = process.env.JWT_SECRET || 'dev-jwt-secret-key-change-in-production-must-be-at-least-32-chars';
const JWT_EXPIRATION = process.env.JWT_EXPIRATION_HOURS || '24';

/**
 * middleware to authenticate jwt tokens
 * adds user object to req.user if token is valid
 */
function authenticateToken(req, res, next) {
  // get token from authorization header
  const authHeader = req.headers['authorization'];
  const token = authHeader && authHeader.split(' ')[1]; // Bearer TOKEN

  if (!token) {
    return res.status(401).json({
      error: 'authentication required',
      message: 'no token provided'
    });
  }

  // verify token
  jwt.verify(token, JWT_SECRET, (err, user) => {
    if (err) {
      // token is invalid or expired
      return res.status(403).json({
        error: 'invalid token',
        message: err.message
      });
    }

    // token is valid, attach user to request
    req.user = user;
    next();
  });
}

/**
 * optional authentication middleware
 * adds user to req.user if token is present and valid
 * but allows request to continue even without token
 */
function optionalAuthentication(req, res, next) {
  const authHeader = req.headers['authorization'];
  const token = authHeader && authHeader.split(' ')[1];

  if (!token) {
    // no token, continue without user
    req.user = null;
    return next();
  }

  jwt.verify(token, JWT_SECRET, (err, user) => {
    if (err) {
      // invalid token, continue without user
      req.user = null;
    } else {
      // valid token, attach user
      req.user = user;
    }
    next();
  });
}

/**
 * generate a jwt token for a user
 *
 * @param {Object} user - user object with id, username, role
 * @param {string} expiresIn - expiration time (e.g., '24h', '7d')
 * @returns {string} jwt token
 */
function generateToken(user, expiresIn = `${JWT_EXPIRATION}h`) {
  const payload = {
    id: user.id,
    username: user.username,
    role: user.role || 'user'
  };

  return jwt.sign(payload, JWT_SECRET, { expiresIn });
}

/**
 * verify a jwt token and return the decoded payload
 *
 * @param {string} token - jwt token to verify
 * @returns {Object|null} decoded user object or null if invalid
 */
function verifyToken(token) {
  try {
    return jwt.verify(token, JWT_SECRET);
  } catch (err) {
    return null;
  }
}

/**
 * middleware to check if user has required role
 * must be used after authenticateToken middleware
 *
 * @param {string|string[]} allowedRoles - role or array of roles
 */
function requireRole(allowedRoles) {
  const roles = Array.isArray(allowedRoles) ? allowedRoles : [allowedRoles];

  return (req, res, next) => {
    if (!req.user) {
      return res.status(401).json({
        error: 'authentication required',
        message: 'no user in request'
      });
    }

    if (!roles.includes(req.user.role)) {
      return res.status(403).json({
        error: 'insufficient permissions',
        message: `requires one of: ${roles.join(', ')}`
      });
    }

    next();
  };
}

/**
 * simple in-memory user storage for development
 * in production, this should be replaced with a proper database
 */
const USERS_FILE = path.join(__dirname, '..', 'data', 'users.json');

function loadUsers() {
  try {
    if (fs.existsSync(USERS_FILE)) {
      const data = fs.readFileSync(USERS_FILE, 'utf8');
      return JSON.parse(data);
    }
  } catch (err) {
    console.error('error loading users:', err);
  }
  return [];
}

function saveUsers(users) {
  try {
    const dir = path.dirname(USERS_FILE);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
    fs.writeFileSync(USERS_FILE, JSON.stringify(users, null, 2));
    return true;
  } catch (err) {
    console.error('error saving users:', err);
    return false;
  }
}

module.exports = {
  authenticateToken,
  optionalAuthentication,
  generateToken,
  verifyToken,
  requireRole,
  loadUsers,
  saveUsers,
  JWT_SECRET
};
