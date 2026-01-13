from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from django.contrib.auth import get_user_model

from small_app.models import Persons

User = get_user_model()


# Create your tests here.
class test_signup(APITestCase):
    # positive testing for sign up
    def test_signup_post_success(self):
        urls = reverse("signup")
        data ={
            "username": "testuser",
            "password": "TestPass123",
            "email": "testuser@example.com"
        }
        response = self.client.post(urls, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(username="testuser").exists())
        self.assertEqual(response.json()["username"], "testuser")
    
    # negative testing for sign up
    def test_signup_post_failure(self):
        urls = reverse("signup")
        data ={
            "username": "",  # Missing username
            "password": "TestPass123",
            "email": "invalidemail"  # Invalid email format
        }
        response = self.client.post(urls, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("username", response.json())
        self.assertIn("email", response.json())

class TestEditMemberDetails(APITestCase):
    def setUp(self):
        # self.user = User.objects.create_user(username="testuser", password="TestPass123", email="testuser@example.com")
        # self.client.login(username="testuser", password="TestPass123")
        self.person = Persons.objects.create(
            first_name="John",
            last_name="Doe",
            email="john.doe@example.com",
            phone_number="1234567890",
            area_of_residence="Test Area"
        )
    def test_modify_person_success(self):
        url = reverse("modify_person", args=[self.person.id])
        data = {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane.doe@example.com",
            "phone_number": "0987654321",
            "area_of_residence": "New Area"
        }
        response = self.client.put(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.person.refresh_from_db()
        self.assertEqual(self.person.first_name, "Jane")
        self.assertEqual(self.person.email, "jane.doe@example.com")
    def test_modify_person_failure(self):
        url = reverse("modify_person", args=[self.person.id])
        data = {
            "first_name": "",  # Invalid: empty first name
            "last_name": "Doe",
            "email": "invalidemail",  # Invalid email format
            "phone_number": "0987654321",
            "area_of_residence": "New Area"
        }
        response = self.client.put(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("first_name", response.json())
        self.assertIn("email", response.json())
       
    