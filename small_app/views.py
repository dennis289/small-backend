from django.shortcuts import render
from .serializers import *
from .models import *
from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import authenticate, get_user_model
from rest_framework_simplejwt.tokens import RefreshToken


User = get_user_model()

# Create your views here.

# signing up users to the system
@api_view(['POST'])
def signup(request):
    if request.method == 'POST':
        serializer = userSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)
    else:
        return Response({"error": "method not allowed"}, status=405)
    
@api_view(['POST'])
def login(request):
    email = request.data.get('email')
    password = request.data.get('password')

    if not email or not password:
        return Response({"error": "Missing email or password"}, status=status.HTTP_400_BAD_REQUEST)
    print(email, password)
    try:
        user_obj = User.objects.get(email=email)
    except User.DoesNotExist:
        return Response({"error": "Invalid credentials"}, status=status.HTTP_400_BAD_REQUEST)

    user = authenticate(username=user_obj.username, password=password)
    if user:
        tokens = get_tokens_for_user(user)  # Generate tokens for the user
        return Response({
            "message": "Login successful",
            "email": user.email,
            "username": user.username,
            "access": tokens['access'],
            "refresh": tokens['refresh']
        }, status=status.HTTP_200_OK)
    else:
        return Response({"error": "Invalid credentials"}, status=status.HTTP_400_BAD_REQUEST)
def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }
<<<<<<< Updated upstream
@api_view(['GET'])
def get_user_info(request):
    user = request.user
    if user.is_authenticated:
        return Response({
            "email": user.email,
            "username": user.username
        }, status=status.HTTP_200_OK)
    else:
        return Response({"error": "User not authenticated"}, status=status.HTTP_401_UNAUTHORIZED)
=======

@api_view(['POST','GET','PUT','DELETE'])
def persons(request):
    if request.method == 'POST':
        serializer = PersonsSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)
    elif request.method == 'GET':
        persons = Persons.objects.all()
        serializer = PersonsSerializer(persons, many=True)
        return Response(serializer.data, status=200)
    elif request.method == 'PUT':
        person_id = request.data.get('id')
        try:
            person = Persons.objects.get(id=person_id)
        except Persons.DoesNotExist:
            return Response({"error": "Person not found"}, status=404)
        
        serializer = PersonsSerializer(person, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)
    elif request.method == 'DELETE':
        person_id = request.data.get('id')
        try:
            person = Persons.objects.get(id=person_id)
            person.delete()
            return Response({"message": "Person deleted successfully"}, status=204)
        except Persons.DoesNotExist:
            return Response({"error": "Person not found"}, status=404)
    else:
        return Response({"error": "Method not allowed"}, status=405)
@api_view(['GET'])
def person_detail(request, pk):
    try:
        person = Persons.objects.get(pk=pk)
    except Persons.DoesNotExist:
        return Response({"error": "Person not found"}, status=404)

    serializer = PersonsSerializer(person)
    return Response(serializer.data, status=200)
>>>>>>> Stashed changes
