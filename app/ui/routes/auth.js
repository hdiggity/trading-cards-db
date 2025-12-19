const express = require('express');
const bcrypt = require('bcrypt');
const { generateToken, authenticateToken, loadUsers, saveUsers } = require('../middleware/auth');

const router = express.Router();

// salt rounds for bcrypt password hashing
const SALT_ROUNDS = 10;

/**
 * POST /api/auth/register
 * register a new user
 */
router.post('/register', async (req, res) => {
  try {
    const { username, password, email } = req.body;

    // validation
    if (!username || !password) {
      return res.status(400).json({
        error: 'validation failed',
        message: 'username and password are required'
      });
    }

    if (password.length < 8) {
      return res.status(400).json({
        error: 'validation failed',
        message: 'password must be at least 8 characters'
      });
    }

    // load existing users
    const users = loadUsers();

    // check if username already exists
    if (users.find(u => u.username === username)) {
      return res.status(409).json({
        error: 'user already exists',
        message: 'username is already taken'
      });
    }

    // check if email already exists
    if (email && users.find(u => u.email === email)) {
      return res.status(409).json({
        error: 'user already exists',
        message: 'email is already registered'
      });
    }

    // hash password
    const passwordHash = await bcrypt.hash(password, SALT_ROUNDS);

    // create new user
    const newUser = {
      id: users.length > 0 ? Math.max(...users.map(u => u.id)) + 1 : 1,
      username,
      email: email || null,
      passwordHash,
      role: users.length === 0 ? 'admin' : 'user', // first user is admin
      createdAt: new Date().toISOString(),
      lastLogin: null
    };

    // add user to users array
    users.push(newUser);

    // save users to file
    if (!saveUsers(users)) {
      return res.status(500).json({
        error: 'registration failed',
        message: 'failed to save user'
      });
    }

    // generate token
    const token = generateToken(newUser);

    // return success without password hash
    res.status(201).json({
      success: true,
      token,
      user: {
        id: newUser.id,
        username: newUser.username,
        email: newUser.email,
        role: newUser.role
      }
    });
  } catch (err) {
    console.error('registration error:', err);
    res.status(500).json({
      error: 'registration failed',
      message: err.message
    });
  }
});

/**
 * POST /api/auth/login
 * authenticate user and return jwt token
 */
router.post('/login', async (req, res) => {
  try {
    const { username, password } = req.body;

    // validation
    if (!username || !password) {
      return res.status(400).json({
        error: 'validation failed',
        message: 'username and password are required'
      });
    }

    // load users
    const users = loadUsers();

    // find user by username
    const user = users.find(u => u.username === username);

    if (!user) {
      return res.status(401).json({
        error: 'invalid credentials',
        message: 'username or password is incorrect'
      });
    }

    // verify password
    const passwordValid = await bcrypt.compare(password, user.passwordHash);

    if (!passwordValid) {
      return res.status(401).json({
        error: 'invalid credentials',
        message: 'username or password is incorrect'
      });
    }

    // update last login
    user.lastLogin = new Date().toISOString();
    saveUsers(users);

    // generate token
    const token = generateToken(user);

    res.json({
      success: true,
      token,
      user: {
        id: user.id,
        username: user.username,
        email: user.email,
        role: user.role,
        lastLogin: user.lastLogin
      }
    });
  } catch (err) {
    console.error('login error:', err);
    res.status(500).json({
      error: 'login failed',
      message: err.message
    });
  }
});

/**
 * POST /api/auth/logout
 * logout user (client should remove token)
 */
router.post('/logout', authenticateToken, (req, res) => {
  // in a jwt-based system, logout is handled client-side by removing the token
  // we could implement a token blacklist here if needed
  res.json({
    success: true,
    message: 'logged out successfully'
  });
});

/**
 * GET /api/auth/me
 * get current user info
 */
router.get('/me', authenticateToken, (req, res) => {
  // load full user data
  const users = loadUsers();
  const user = users.find(u => u.id === req.user.id);

  if (!user) {
    return res.status(404).json({
      error: 'user not found',
      message: 'user no longer exists'
    });
  }

  res.json({
    user: {
      id: user.id,
      username: user.username,
      email: user.email,
      role: user.role,
      createdAt: user.createdAt,
      lastLogin: user.lastLogin
    }
  });
});

/**
 * PUT /api/auth/change-password
 * change user password
 */
router.put('/change-password', authenticateToken, async (req, res) => {
  try {
    const { currentPassword, newPassword } = req.body;

    // validation
    if (!currentPassword || !newPassword) {
      return res.status(400).json({
        error: 'validation failed',
        message: 'current password and new password are required'
      });
    }

    if (newPassword.length < 8) {
      return res.status(400).json({
        error: 'validation failed',
        message: 'new password must be at least 8 characters'
      });
    }

    // load users
    const users = loadUsers();
    const user = users.find(u => u.id === req.user.id);

    if (!user) {
      return res.status(404).json({
        error: 'user not found',
        message: 'user no longer exists'
      });
    }

    // verify current password
    const passwordValid = await bcrypt.compare(currentPassword, user.passwordHash);

    if (!passwordValid) {
      return res.status(401).json({
        error: 'invalid password',
        message: 'current password is incorrect'
      });
    }

    // hash new password
    user.passwordHash = await bcrypt.hash(newPassword, SALT_ROUNDS);

    // save users
    if (!saveUsers(users)) {
      return res.status(500).json({
        error: 'password change failed',
        message: 'failed to save new password'
      });
    }

    res.json({
      success: true,
      message: 'password changed successfully'
    });
  } catch (err) {
    console.error('password change error:', err);
    res.status(500).json({
      error: 'password change failed',
      message: err.message
    });
  }
});

/**
 * GET /api/auth/users
 * list all users (admin only)
 */
router.get('/users', authenticateToken, (req, res) => {
  // check if user is admin
  if (req.user.role !== 'admin') {
    return res.status(403).json({
      error: 'insufficient permissions',
      message: 'admin role required'
    });
  }

  const users = loadUsers();

  // return users without password hashes
  const userList = users.map(u => ({
    id: u.id,
    username: u.username,
    email: u.email,
    role: u.role,
    createdAt: u.createdAt,
    lastLogin: u.lastLogin
  }));

  res.json({ users: userList });
});

module.exports = router;
